"""Python observes requests; only the Go transport can reject model quota admission."""

from types import SimpleNamespace

import pytest
from test_local_go_gateway import gateway_fixture

from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
from roami_agent.improvement.integrations.request_model import RequestBudgetModel
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.persistence.research_costs import ResearchCosts
from roami_agent.improvement.persistence.run_costs import RunCosts
from roami_agent.improvement.workflows.model_calls import model_json
from roami_agent.protocol.errors import DomainError, ModelAdmissionRejected
from roami_agent.protocol.models import ModelEvent
from roami_agent.providers.factory import configured_provider
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize("shared", [False, True])
async def test_python_zero_allowance_still_sends_unchanged_requests_to_go(
    tmp_path, monkeypatch, shared
):
    socket = str(tmp_path / "model.sock")
    monkeypatch.setenv("ROAMI_MODEL_GATEWAY_SOCKET", socket)
    settings = Settings(
        endpoint="https://must-not-connect.invalid/v1",
        model="saved-model",
        model_parameters={"max_tokens": 8192, "temperature": 0.4},
    )
    usage = EpisodeBudget({"tokens": 0, "requests": 0, "seconds": 0}, shared_daily_limit=shared)
    model = RequestBudgetModel(settings, settings.route("worker"), usage, "worker", cap=512)
    messages = [{"role": "user", "content": "A self-contained fixture request"}]
    seen = []
    async with gateway_fixture(socket, seen):
        for _ in range(3):
            assert [e.value async for e in model.stream(messages, []) if e.kind == "text"] == [
                "hello"
            ]
    assert len(seen) == 3 and usage.metrics()["tokens"] == 3300
    assert all(
        body["messages"] == messages and body["max_tokens"] == 8192 and body["temperature"] == 0.4
        for _, _, body in seen
    )


async def test_go_quota_rejection_remains_authoritative_even_with_zero_python_limits(
    tmp_path, monkeypatch
):
    socket = str(tmp_path / "model.sock")
    monkeypatch.setenv("ROAMI_MODEL_GATEWAY_SOCKET", socket)
    settings = Settings(endpoint="https://must-not-connect.invalid/v1", model="saved-model")
    usage = EpisodeBudget({"tokens": 0, "requests": 0, "seconds": 0})
    model = RequestBudgetModel(settings, settings.route("main"), usage, "main")
    seen = []
    async with gateway_fixture(socket, seen, status=402, code="MODEL_PROXY_DAILY_LIMIT"):
        with pytest.raises(ModelAdmissionRejected, match="MODEL_PROXY_DAILY_LIMIT"):
            async for _ in model.stream([], []):
                pass
    assert len(seen) == 1 and usage.metrics()["tokens"] == 0
    assert usage.metrics()["requests"][0]["requestAttempts"] == 0


async def test_missing_go_binding_never_creates_a_direct_upstream_client(monkeypatch):
    monkeypatch.delenv("ROAMI_MODEL_GATEWAY_SOCKET", raising=False)

    import httpx

    async def forbidden(self, request):
        raise AssertionError("Missing Go binding must never open an upstream transport")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    provider = configured_provider(
        Settings(endpoint="https://must-not-connect.invalid/v1", model="saved-model"), "main"
    )
    try:
        with pytest.raises(ModelAdmissionRejected, match="MODEL_GATEWAY_REQUIRED"):
            async for _ in provider.stream([], []):
                pass
    finally:
        await provider.close()


async def test_unknown_python_measurement_does_not_make_an_admission_decision():
    calls = []

    class Model:
        model = "usage-fixture"

        async def stream(self, *args):
            calls.append(True)
            yield ModelEvent("text", "response")
            if len(calls) > 1:
                yield ModelEvent(
                    "usage",
                    {
                        "inputTokens": 9,
                        "outputTokens": 1,
                        "requestAttempts": 1,
                        "retryUsageKnown": True,
                    },
                )

    usage = EpisodeBudget({"tokens": 1, "requests": 1, "seconds": 0})
    model = MeteredModel(Model(), usage, "main")
    for _ in range(2):
        assert [e.value async for e in model.stream([], []) if e.kind == "text"] == ["response"]
    assert len(calls) == 2 and usage.metrics()["tokens"] is None
    assert (
        usage.metrics()["observed_tokens"] == 10 and usage.metrics()["token_coverage"] == "unknown"
    )


def test_research_accounting_does_not_freeze_or_spend_a_python_budget(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    costs = ResearchCosts(SimpleNamespace(ledger=ledger))
    with ledger.connection() as db:
        db.execute("INSERT INTO rsi_budgets VALUES('local','2026-10-30',1,1,1,1)")
    assert costs.reserve_operation("local", "2026-10-30", "one", 1000000) is None
    costs.settle_operation("local", "one", {"value": {"metrics": {"tokens": None}}})
    assert costs.reserve_operation("local", "2026-10-30", "two", 1000000) is None
    with pytest.raises(DomainError, match="RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION"):
        costs.reserve_operation("local", "2026-10-30", "one", 0)
    with ledger.connection() as db:
        assert tuple(
            db.execute(
                "SELECT tokens_limit,episodes_limit,tokens_reserved,episodes_reserved FROM rsi_budgets"
            ).fetchone()
        ) == (1, 1, 1, 1)
        assert [r[0] for r in db.execute("SELECT reserved FROM rsi_operation_costs")] == [0, 0]


def test_run_accounting_ignores_pipeline_quota_and_unrelated_unknown_operations(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    records = SimpleNamespace(
        ledger=ledger,
        get=lambda *args: {
            "snapshot": {"pipeline": {"codex_tokens": 0}},
            "summary": {"generation_tokens": None},
        },
    )
    costs = RunCosts(records, "local", "run")
    assert costs.reserve_operation("local", "2026-10-30", "one", 1000000) is None
    assert costs.reserve_operation("local", "2026-10-30", "two", 1000000) is None
    with pytest.raises(DomainError, match="RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION"):
        costs.reserve_operation("local", "2026-10-30", "one", 0)
    with ledger.connection() as db:
        assert [r[0] for r in db.execute("SELECT reserved FROM rsi_pipeline_costs")] == [0, 0]


async def test_semantic_model_preserves_node_parameters_and_reuses_completed_operation(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    costs = ResearchCosts(SimpleNamespace(ledger=ledger))
    workflow = SimpleNamespace(
        day=lambda owner: "2026-10-30",
        reserve_operation=costs.reserve_operation,
        settle_operation=costs.settle_operation,
    )
    settings = Settings(
        endpoint="https://must-not-connect.invalid/v1",
        model="saved-main",
        model_parameters={"max_tokens": 32768, "temperature": 0.4},
        model_retries=3,
    )
    observed = []

    class Model:
        model = "fixture"

        async def stream(self, *args):
            yield ModelEvent("text", "{}")
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 60000,
                    "outputTokens": 40000,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    def factory(effective):
        observed.append(effective.route("main"))
        return Model()

    args = (
        workflow,
        {"id": "action", "owner": "local", "kind": "review"},
        settings,
        {"model_tokens": 1, "model_seconds": 5},
        "result",
        [],
    )
    first = await model_json(*args, provider_factory=factory)
    assert first["metrics"]["tokens"] == 100000
    assert await model_json(*args, provider_factory=factory) == first
    assert (
        len(observed) == 1
        and observed[0].parameters == settings.model_parameters
        and observed[0].max_retries == 3
    )


async def test_daily_brief_schedule_count_has_no_framework_quota(store):
    from test_daily_briefs import fixture

    briefs, _, _, conversation, _, _ = await fixture(store)
    for number in range(5):
        assert (
            await briefs.create(
                "alice", conversation["id"], "A separate brief", str(number), daily_at="09:00"
            )
        )["enabled"]
    assert len(await briefs.list("alice")) == 6


async def test_silent_proactive_evaluations_have_no_hourly_or_daily_model_quota(store):
    from test_proactive_jobs import (
        ConversationModel,
        SuggestionModel,
        completed_task,
        enable,
        verified,
    )

    from roami_agent.app import Runtime

    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel('{"send":false,"text":""}')
    runtime.proactive.model = model
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        for key in ["one", "two", "three", "four"]:
            await completed_task(runtime, key=key)
        for _ in range(4):
            await runtime.proactive.tick()
        assert len(model.calls) == 4
    finally:
        await runtime.close()


@pytest.mark.parametrize("section", ["proactive", "briefs"])
def test_legacy_daily_budget_is_not_an_agent_quota_configuration(tmp_path, section):
    path = tmp_path / "agent.toml"
    path.write_text("[" + section + "]\ndaily_budget=0\n")
    settings = Settings.load(path)
    assert not hasattr(settings, "brief_daily_budget") and not hasattr(
        settings, "proactive_daily_budget"
    )


@pytest.mark.parametrize("limits", [{"seconds": 30}, {"seconds": 30, "tokens": 0, "requests": 0}])
def test_case_quota_fields_are_optional_and_never_reach_the_actor(tmp_path, limits):
    from test_improvement import case

    from roami_agent.improvement.evaluation.contracts import agent_view, freeze_suite

    original = case(limits=limits)
    frozen = freeze_suite("no-python-quota", [original])
    assert frozen["cases"][0]["limits"] == limits
    view = agent_view(frozen["cases"][0], tmp_path)
    assert view["limits"] == {"seconds": 30}
    assert original["limits"] == limits
