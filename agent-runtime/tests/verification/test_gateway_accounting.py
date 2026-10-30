"""Python observes requests; only the Go transport can reject model quota admission."""

from types import SimpleNamespace

import pytest

from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.persistence.research_costs import ResearchCosts
from roami_agent.improvement.persistence.run_costs import RunCosts
from roami_agent.improvement.workflows.model_calls import model_json
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


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
