import json
from types import SimpleNamespace

import pytest
from test_improvement_control import suite_file

from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.github_client import configure_publication
from roami_agent.improvement.persistence.run_costs import RunCosts
from roami_agent.improvement.service import ImprovementStatus
from roami_agent.improvement.workflows.pipeline_reports import publish_run_issue
from roami_agent.improvement.workflows.pipeline_runner import enqueue_diagnostic
from roami_agent.protocol.errors import DomainError


def setup_run(tmp_path, key="one", case_ids=None):
    service = ImprovementStatus(tmp_path)
    records = service.runs
    run_id = records.create(
        "local",
        key,
        "diagnostic",
        {"pipeline": records.settings("local"), "case_ids": case_ids or ["a"]},
    )
    return service, run_id


def outcome(*, signal=None, passed=False, tokens=10, version=1):
    return trial_summary(
        {"id": "a", "version": version},
        {"grade": {"passed": passed, "reason": signal}, "metrics": {"tokens": tokens}},
    )


def test_owner_artifact_integrity_and_stage_identity(tmp_path):
    service, run_id = setup_run(tmp_path)
    records = service.runs
    with pytest.raises(DomainError, match="RUN_NOT_FOUND"):
        records.artifact("other", run_id, "review", "report.md", "x")
    for stage in ("review", "issue"):
        records.artifact("local", run_id, stage, "report.md", stage)
    value = records.get("local", run_id)
    assert len(value["artifacts"]) == 2
    for artifact in value["artifacts"]:
        assert records.read_artifact("local", run_id, artifact["id"])["text"] == artifact["node"]
    with pytest.raises(DomainError, match="ARTIFACT_CHANGED"):
        records.artifact("local", run_id, "review", "report.md", "changed")
    with pytest.raises(DomainError, match="RUN_NOT_FOUND"):
        records.read_artifact("other", run_id, value["artifacts"][0]["id"])
    path = records.directory("local", run_id) / "review/report.md"
    path.write_text("tampered")
    with pytest.raises(DomainError, match="ARTIFACT_CHANGED"):
        records.read_artifact(
            "local", run_id, next(a["id"] for a in value["artifacts"] if a["node"] == "review")
        )


@pytest.mark.parametrize(
    ("passed", "tokens", "version", "included", "expected"),
    [
        (True, 10, 1, True, "not_reproduced"),
        (True, None, 1, True, "unverified"),
        (False, 10, 1, True, "unverified"),
        (True, 10, 2, True, "not_comparable"),
        (True, 10, 1, False, "not_tested"),
    ],
)
def test_recurrence_requires_same_contract_and_known_pass(
    tmp_path, passed, tokens, version, included, expected
):
    service, baseline = setup_run(tmp_path)
    records = service.runs
    records.case("local", baseline, outcome(signal="WORKSPACE_REQUIRED"))
    records.observations("local", baseline)
    second = records.create("local", "two", "diagnostic", {"pipeline": records.settings("local")})
    if included:
        records.case("local", second, outcome(passed=passed, tokens=tokens, version=version))
    records.observations("local", second)
    assert records.get("local", second)["issues"][0]["status"] == expected
    assert records.get("local", baseline)["issues"][0]["status"] == "present"


def test_diagnostic_queue_is_idempotent_and_admission_is_atomic(tmp_path):
    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    control = service.control
    control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    control.register_suite("local", suite_file(tmp_path))
    prefs = control.preferences("local")
    control.save("local", {**prefs, "suite_id": "data", "machine_ids": ["a"]})
    first = enqueue_diagnostic(service, "local", {"request_key": "one", "case_ids": ["a"]})
    assert first == enqueue_diagnostic(service, "local", {"request_key": "one", "case_ids": ["a"]})
    assert len(control.requests("local")) == 1
    control.cancel("local", first["id"])
    assert service.runs.get("local", first["id"])["state"] == "cancelled"
    enqueue_diagnostic(service, "local", {"request_key": "two", "case_ids": ["a"]})
    enqueue_diagnostic(service, "local", {"request_key": "three", "case_ids": ["a"]})
    with service.ledger.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_budgets").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM rsi_pipeline_runs").fetchone()[0] == 3
    service.runs.configure("local", {"revision": 0, "auto_publish": True})
    assert service.runs.settings("local")["auto_publish"]


def test_unknown_codex_cost_prevents_paid_replay(tmp_path):
    service, run_id = setup_run(tmp_path)
    costs = RunCosts(service.runs, "local", run_id)
    assert costs.reserve_operation("local", "today", "first", 64000) is None
    with pytest.raises(DomainError, match="RECONCILIATION"):
        costs.reserve_operation("local", "today", "first", 64000)
    assert costs.reserve_operation("local", "today", "second", 64000) is None
    costs.settle_operation("local", "first", {"value": {"metrics": {"tokens": 50}}})
    assert (
        costs.reserve_operation("local", "today", "first", 64000)["value"]["metrics"]["tokens"]
        == 50
    )


@pytest.mark.asyncio
async def test_github_unknown_post_reconciles_without_duplicate(tmp_path):
    service, run_id = setup_run(tmp_path)
    records = service.runs
    records.set_state("local", run_id, "completed", {"cases": 1})
    configure_publication(
        records.ledger.path.parent,
        "local",
        {"repository": "example/test", "remote": "origin", "base": "main"},
    )
    remote, posts = [], []

    async def command(argv, **kwargs):
        if "POST" in argv:
            payload = json.loads(kwargs["data"])
            posts.append(payload)
            remote.append(
                {
                    "number": 1,
                    "html_url": "https://github.com/example/test/issues/1",
                    "body": payload["body"],
                }
            )
            raise OSError("response lost")
        return json.dumps(remote if "?" in argv[-1] else remote[0])

    with pytest.raises(OSError):
        await publish_run_issue(records, "local", run_id, {}, run=command)
    receipt = await publish_run_issue(records, "local", run_id, {}, run=command)
    assert receipt["number"] == 1
    assert len(posts) == 1
    assert records.get("local", run_id)["issue"] == receipt


def test_cancelled_evaluation_never_queues_paid_report(tmp_path):
    service, run_id = setup_run(tmp_path)
    with service.ledger.connection() as db:
        db.execute(
            "INSERT INTO rsi_requests VALUES(?,?,?,'manual','interrupted',1,1,NULL,NULL,'RSI_CANCELLED',?)",
            (run_id, "local", "a", json.dumps({"diagnostic": {}})),
        )
    service.run_lifecycle.capture_request({"owner": "local", "id": run_id})
    assert service.runs.get("local", run_id)["state"] == "cancelled"
    assert service.runs.claim_report() is None


@pytest.mark.asyncio
async def test_pipeline_http_is_owner_scoped_and_publication_requires_target(store):
    import httpx

    from roami_agent.app import Runtime
    from roami_agent.server.http import create_app

    runtime = Runtime(store, SimpleNamespace(model="fixture"), development_rsi=True)
    records = runtime.improvement.runs
    run_id = records.create("local", "api", "diagnostic", {"pipeline": records.settings("local")})
    records.artifact("local", run_id, "review", "review.md", "# Real report")
    artifact = records.get("local", run_id)["artifacts"][0]["id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://fixture",
    ) as client:
        path = "/v1/improvement/pipeline/runs/" + run_id
        assert (await client.get(path, headers={"X-Roami-Owner": "local"})).status_code == 200
        assert (await client.get(path, headers={"X-Roami-Owner": "other"})).status_code == 404
        response = await client.get(
            path + "/artifacts/" + artifact, headers={"X-Roami-Owner": "local"}
        )
        assert response.json()["data"]["text"] == "# Real report"
        response = await client.put(
            "/v1/improvement/pipeline/settings",
            headers={"X-Roami-Owner": "local"},
            json={**records.settings("local"), "auto_publish": True},
        )
        assert response.json()["error"]["code"] == "RSI_PUBLICATION_SETUP_REQUIRED"


def test_formal_case_contract_survives_preflight_and_missing_logs_are_unknown(tmp_path):
    service = ImprovementStatus(tmp_path)
    suite = {"content_hash": "frozen", "cases": [{"id": "a"}, {"id": "b"}]}
    run_id = service.runs.create(
        "local",
        "formal",
        "daily",
        {"pipeline": service.runs.settings("local"), "suite_hash": "frozen", "case_ids": []},
    )
    service.run_lifecycle.freeze_cases("local", run_id, suite)
    assert service.runs.get("local", run_id)["snapshot"]["case_ids"] == ["a", "b"]
    with pytest.raises(DomainError, match="CASES_CHANGED"):
        service.run_lifecycle.freeze_cases("local", run_id, {**suite, "cases": [{"id": "b"}]})
    value = trial_summary(
        {"id": "a"}, {"grade": {"passed": False}, "metrics": {"tokens": None}}, tmp_path / "missing"
    )
    assert value["tool_calls"] is None


def test_empty_baseline_is_rejected_before_diagnostic_admission(tmp_path):
    service = ImprovementStatus(tmp_path)
    run_id = service.runs.create(
        "local", "old-empty", "daily", {"pipeline": service.runs.settings("local"), "case_ids": []}
    )
    with pytest.raises(DomainError, match="CASES_UNAVAILABLE"):
        enqueue_diagnostic(service, "local", {"request_key": "bad", "baseline_run": run_id})
    with service.ledger.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_budgets").fetchone()[0] == 0


def test_memory_route_is_optional_frozen_and_validated(tmp_path):
    service = ImprovementStatus(tmp_path)
    old = service.runs.settings("local")
    legacy = {k: v for k, v in old.items() if k not in {"memory_model", "memory_reasoning_effort"}}
    current = service.runs.configure("local", legacy)
    result = service.runs.configure(
        "local", {**current, "memory_model": "glm-5.3-flash", "memory_reasoning_effort": "low"}
    )
    assert set(result) == {"revision", "auto_publish"}
    ignored = service.runs.configure("local", {**result, "memory_model": "bad\nmodel"})
    assert set(ignored) == {"revision", "auto_publish"}


def test_daily_artifact_admission_has_no_reservation_and_unknown_operations_do_not_spend_again(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from roami_agent.improvement.evaluation.contracts import freeze_suite, load_suite
    from roami_agent.server.configuration import Settings

    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    base = load_suite(suite_file(tmp_path))["cases"][0]
    suite = freeze_suite("rated", [{**base, "id": name} for name in ("DOC-05", "DEMO-01")])
    path = tmp_path / "rated.json"
    path.write_text(json.dumps(suite))
    service.control.register_suite("local", path)
    prefs = service.control.preferences("local")
    service.control.save("local", {**prefs, "suite_id": "rated", "machine_ids": ["a"]})
    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.artifact_review.ArtifactReviewer.load",
        lambda *args, **kwargs: SimpleNamespace(
            content_hash="qualified-rater", profile={"max_tokens": 50000}
        ),
    )
    first = enqueue_diagnostic(
        service,
        "local",
        {"request_key": "rated-one", "case_ids": ["DOC-05", "DEMO-01"]},
        Settings(),
    )
    run = service.runs.get("local", first["id"])
    assert run["snapshot"]["artifact_review"] == {
        "hash": "qualified-rater",
        "reservation_tokens": 0,
    }
    with service.ledger.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_budgets").fetchone()[0] == 0
        db.execute(
            "INSERT INTO rsi_operation_costs VALUES('unknown','local','today',100,'unknown',NULL)"
        )
    assert (
        enqueue_diagnostic(
            service, "local", {"request_key": "rated-one", "case_ids": ["DOC-05", "DEMO-01"]}
        )
        == first
    )
    assert (
        enqueue_diagnostic(
            service, "local", {"request_key": "new", "case_ids": ["DOC-05"]}, Settings()
        )["id"]
        != first["id"]
    )
    with service.ledger.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_budgets").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["generation_tokens", "artifact_review_tokens"])
def test_unknown_evaluation_usage_does_not_own_go_admission(tmp_path, field):
    service, run_id = setup_run(tmp_path)
    service.runs.set_state("local", run_id, "report_queued", {field: None})
    costs = RunCosts(service.runs, "local", run_id)
    assert costs.reserve_operation("local", "today", "review", 64000) is None
    with service.ledger.connection() as db:
        assert db.execute("SELECT reserved FROM rsi_pipeline_costs").fetchone()[0] == 0


def test_unrelated_unknown_calibration_does_not_own_go_admission(tmp_path):
    service, run_id = setup_run(tmp_path)
    with service.ledger.connection() as db:
        db.execute(
            "INSERT INTO rsi_operation_costs VALUES('calibration','local','today',100,'unknown',NULL)"
        )
    assert (
        RunCosts(service.runs, "local", run_id).reserve_operation("local", "today", "review", 64000)
        is None
    )


@pytest.mark.asyncio
async def test_unknown_artifact_usage_preserves_measurement_without_local_quota(
    tmp_path, monkeypatch
):
    from roami_agent.improvement.evaluation.contracts import freeze_suite, load_suite
    from roami_agent.improvement.workflows.pipeline_runner import execute_diagnostic
    from roami_agent.server.configuration import Settings

    service = ImprovementStatus(tmp_path)
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    base = load_suite(suite_file(tmp_path))["cases"][0]
    base["limits"]["tokens"] = 384000
    path = tmp_path / "two.json"
    path.write_text(json.dumps(freeze_suite("two", [{**base, "id": name} for name in ("a", "b")])))
    service.control.register_suite("local", path)
    service.control.save(
        "local", {**service.control.preferences("local"), "suite_id": "two", "machine_ids": ["a"]}
    )
    run = enqueue_diagnostic(service, "local", {"request_key": "two", "case_ids": ["a", "b"]})
    calls = []

    class Executor:
        model_hash = "b" * 64

        def __init__(self, *args, **kwargs):
            pass

        async def preflight(self):
            return {"environment_hash": "a" * 64}

        async def run(self, case, policy, target):
            calls.append((case["id"], case["limits"]["tokens"]))
            return {
                "grade": {"passed": False},
                "metrics": {"tokens": None, "artifact_review_tokens": None},
            }

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.execution.containers.ContainerExecutor", Executor
    )
    await execute_diagnostic(
        SimpleNamespace(settings=SimpleNamespace(current=Settings())),
        service,
        service.control.claim(),
    )
    value = service.runs.get("local", run["id"])
    assert calls == [("a", 384000), ("b", 384000)]
    budgets = [
        json.loads(service.runs.read_artifact("local", run["id"], a["id"])["text"])
        for a in value["artifacts"]
        if a["name"].startswith("budget-") and a["name"] != "budget-plan.json"
    ]
    first = next(b for b in budgets if b["case_id"] == "a")
    assert first["original_limits"]["tokens"] == 384000
    assert first["effective_limits"]["tokens"] is None
    assert first["reserved_for_later_cases"] is None
    assert value["summary"]["artifact_review_tokens"] is None
    assert all("blocked_by" not in case for case in value["cases"])
    assert value["summary"]["not_run"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rejection",
    [None, "MODEL_PROXY_USAGE_UNKNOWN", "MODEL_PROXY_DAILY_LIMIT", "MODEL_PROXY_CURRENCY_MISMATCH"],
)
async def test_unknown_generation_keeps_one_cause_and_a_free_summary(
    tmp_path, monkeypatch, rejection
):
    from functools import partial

    from roami_agent.improvement.evaluation.contracts import freeze_suite, load_suite
    from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
    from roami_agent.improvement.workflows.codex_roles import codex_json
    from roami_agent.improvement.workflows.pipeline_reports import PipelineReportWorker
    from roami_agent.improvement.workflows.pipeline_runner import execute_diagnostic
    from roami_agent.protocol.errors import ModelAdmissionRejected
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.server.configuration import Settings

    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = rejection is not None
    service.control.register_machine(
        "local", {"id": "container", "label": "Container", "mode": "container"}, local_only=True
    )
    base = load_suite(suite_file(tmp_path))["cases"][0]
    cases = [{**base, "id": name} for name in ("root", "later-a", "later-b")]
    cases.insert(2, {**base, "id": "mechanism", "judge": {"kind": "mechanism"}})
    suite = tmp_path / "causal.json"
    suite.write_text(json.dumps(freeze_suite("causal", cases)))
    service.control.register_suite("local", suite)
    service.control.save(
        "local",
        {
            **service.control.preferences("local"),
            "suite_id": "causal",
            "machine_ids": ["container"],
        },
    )
    settings, calls = Settings(), []

    class Interrupted:
        model = "interrupted-fixture"

        async def stream(self, messages, tools):
            if rejection:
                raise ModelAdmissionRejected(rejection)
            yield ModelEvent("text", "partial")

    service.provider_factory = lambda *args: Interrupted()

    class Executor(ContainerExecutor):
        async def preflight(self):
            return {"environment_hash": "a" * 64}

        async def run(self, case, policy, target):
            calls.append(case["id"])
            if case["judge"]["kind"] == "mechanism":
                return {"grade": {"passed": True}, "metrics": {"tokens": 0, "model_calls": 0}}
            provider = self.provider_factory(settings, "memory")
            reason = "RSI_USAGE_UNKNOWN"
            try:
                async for _ in provider.stream([{"role": "user", "content": "memory"}], []):
                    pass
            except ModelAdmissionRejected as exc:
                reason = exc.code
            return {
                "grade": {"passed": False, "reason": reason},
                "metrics": self.shared_budget.metrics(),
            }

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.execution.containers.ContainerExecutor", Executor
    )
    receipt = enqueue_diagnostic(
        service, "local", {"request_key": "causal", "case_ids": [c["id"] for c in cases]}
    )
    await execute_diagnostic(
        SimpleNamespace(settings=SimpleNamespace(current=settings)),
        service,
        service.control.claim(),
    )
    value = service.runs.get("local", receipt["id"])
    if rejection is None:
        assert calls == ["root", "later-a", "mechanism", "later-b"]
        assert value["summary"]["generation_tokens"] is None
        assert value["summary"]["not_run"] == 0
        assert not value["summary"].get("usage_blocker")
        assert all("blocked_by" not in case for case in value["cases"])
        assert any(a["name"] == "evaluation-summary.md" for a in value["artifacts"])
        return
    assert calls == ["root", "mechanism"]
    cause = rejection or "RSI_USAGE_UNKNOWN"
    assert value["summary"]["generation_tokens"] == (0 if rejection else None)
    assert value["summary"]["provider_requests"] == (0 if rejection else None)
    assert value["summary"]["blocked"] == 3 and value["summary"]["not_run"] == 2
    assert value["summary"]["usage_blocker"] == {"case_id": "root", "code": cause}
    assert all(i["case_id"] == "root" for i in value["issues"])
    if rejection != "MODEL_PROXY_DAILY_LIMIT":
        assert [(i["case_id"], i["code"]) for i in value["issues"]] == [("root", cause)]
    for case in value["cases"]:
        if case["case_id"].startswith("later-"):
            assert case["state"] == "blocked" and not case["passed"]
            assert case["metrics"]["tokens"] == case["metrics"]["model_calls"] == 0
            assert case["blocked_by"]["case_id"] == "root"
    artifact = next(a for a in value["artifacts"] if a["name"] == "evaluation-summary.md")
    text = service.runs.read_artifact("local", receipt["id"], artifact["id"])["text"]
    assert f"| `later-a` | `root` | `{cause}` |" in text
    assert "Codex 复盘与独立验收以对应环节的回执为准" in text

    async def forbidden(*args, **kwargs):
        pytest.fail("Unknown generation usage must block paid Codex before starting it")

    monkeypatch.setattr(
        "roami_agent.improvement.workflows.codex_roles.codex_configuration",
        lambda: ({"model": "fixture"}, {}),
    )
    monkeypatch.setattr(
        "roami_agent.improvement.workflows.pipeline_reports.codex_json",
        partial(codex_json, runner=forbidden),
    )
    if rejection:

        async def reject():
            raise DomainError(rejection)

        class Proxy:
            billing = SimpleNamespace(check=reject)

            async def ready(self):
                pass

        service.runs.model_proxy = Proxy()
    await PipelineReportWorker(service).execute(service.runs.claim_report())
    blocked = service.runs.get("local", receipt["id"])
    assert blocked["state"] == "blocked"
    assert next(n for n in blocked["nodes"] if n["node"] == "review")["error_code"] == cause
    assert service.runs.read_artifact("local", receipt["id"], artifact["id"])["text"] == text
    assert not any(a["name"] == "review.md" for a in blocked["artifacts"])


def test_cascade_block_is_not_a_reproduction_of_an_older_issue(tmp_path):
    service, first = setup_run(tmp_path)
    records = service.runs
    records.case("local", first, outcome(signal="RSI_USAGE_UNKNOWN"))
    records.observations("local", first)
    second = records.create("local", "second", "diagnostic", {"case_ids": ["a"]})
    blocked = outcome(signal="RSI_USAGE_UNKNOWN", tokens=0)
    blocked["blocked_by"] = {"case_id": "other", "code": "RSI_USAGE_UNKNOWN"}
    records.case("local", second, blocked)
    records.observations("local", second)
    assert records.get("local", second)["issues"][0]["status"] == "unverified"
    assert records.get("local", first)["issues"][0]["status"] == "present"


def test_quarantine_keeps_full_cost_unknown_and_cannot_replay(tmp_path):
    from roami_agent.improvement.persistence.operation_accounting import quarantine_operation

    service = ImprovementStatus(tmp_path)
    evidence = tmp_path / "receipt.json"
    evidence.write_text('{"error":"MODEL_DEADLINE","requests":1,"local_process_ended":true}')
    with service.ledger.connection() as db:
        db.execute("INSERT INTO rsi_budgets VALUES('local','today',1000000,20,100000,0)")
        db.execute(
            "INSERT INTO rsi_operation_costs VALUES('old','local','today',100000,'unknown',?)",
            (json.dumps({"value": {"metrics": {"tokens": None}}}),),
        )
    workflow = service.research
    assert workflow.reserve_operation("local", "today", "independent", 10000) is None
    with pytest.raises(DomainError, match="NOT_FOUND"):
        quarantine_operation(
            service.ledger,
            "other",
            "old",
            reason="Ended local request; retain full reservation",
            evidence=evidence,
        )
    receipt = quarantine_operation(
        service.ledger,
        "local",
        "old",
        reason="Ended local request; retain full reservation",
        evidence=evidence,
    )
    assert receipt["reservation_retained"] == 100000
    assert workflow.reserve_operation("local", "today", "new", 10000) is None
    with pytest.raises(DomainError, match="RECONCILIATION"):
        workflow.reserve_operation("local", "today", "old", 100000)
    with service.ledger.connection() as db:
        assert db.execute("SELECT tokens_reserved FROM rsi_budgets").fetchone()[0] == 100000
        result = json.loads(
            db.execute("SELECT result_json FROM rsi_operation_costs WHERE id='old'").fetchone()[0]
        )
        assert result["value"]["metrics"]["tokens"] is None


def test_missing_optional_fields_preserve_saved_role_routes(tmp_path):
    service = ImprovementStatus(tmp_path)
    settings = service.runs.settings("local")
    saved = service.runs.configure(
        "local", {**settings, "worker_model": "glm-5.3-flash", "worker_reasoning_effort": "low"}
    )
    legacy = {
        k: v
        for k, v in saved.items()
        if not k.startswith(("worker_", "memory_model", "memory_reasoning"))
    }
    assert set(service.runs.configure("local", legacy)) == {"revision", "auto_publish"}


def test_operation_usage_is_durable_and_legacy_budget_is_never_changed(tmp_path):
    service = ImprovementStatus(tmp_path)
    with service.ledger.connection() as db:
        db.execute("INSERT INTO rsi_budgets VALUES('local','today',100000,20,0,0)")
    workflow = service.research
    workflow.reserve_operation("local", "today", "one", 50000)
    workflow.settle_operation("local", "one", {"value": {"metrics": {"tokens": 1000}}})
    with service.ledger.connection() as db:
        assert db.execute("SELECT tokens_reserved FROM rsi_budgets").fetchone()[0] == 0
    with pytest.raises(DomainError, match="CONFLICT"):
        workflow.settle_operation("local", "one", {"value": {"metrics": {"tokens": 1000}}})
    workflow.reserve_operation("local", "today", "two", 50000)
    workflow.settle_operation("local", "two", {"value": {"metrics": {"tokens": None}}})
    with service.ledger.connection() as db:
        assert db.execute("SELECT tokens_reserved FROM rsi_budgets").fetchone()[0] == 0
        assert (
            db.execute("SELECT state FROM rsi_operation_costs WHERE id='two'").fetchone()[0]
            == "unknown"
        )


def test_legacy_unknown_receipt_remains_visible_without_local_quota(tmp_path):
    service = ImprovementStatus(tmp_path)
    with service.ledger.connection() as db:
        db.execute("INSERT INTO rsi_budgets VALUES('local','today',100000,20,50000,0)")
        db.execute(
            "INSERT INTO rsi_operation_costs VALUES('legacy','local','today',50000,'completed',?)",
            (json.dumps({"value": {"metrics": {"tokens": None}}}),),
        )
    assert service.research.reserve_operation("local", "today", "new", 1000) is None


def test_diagnostic_header_allows_later_formal_budget_reservation(tmp_path):
    service = ImprovementStatus(tmp_path)
    control = service.control
    control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    control.register_suite("local", suite_file(tmp_path))
    control.save(
        "local", {**control.preferences("local"), "suite_id": "data", "machine_ids": ["a"]}
    )
    enqueue_diagnostic(service, "local", {"request_key": "diagnostic", "case_ids": ["a"]})
    day = service.research.day("local")
    with service.ledger.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_budgets").fetchone()[0] == 0
    cycle, admitted = service.ledger.reserve(
        "local",
        day,
        {
            "reserved_tokens": 1000,
            "reserved_episodes": 1,
            "machine": {"id": "a"},
            "request_key": "formal-budget-check",
        },
        tokens_limit=0,
        episodes_limit=120,
    )
    assert admitted and cycle


def test_diagnostics_ignore_removed_python_episode_cap(tmp_path):
    service = ImprovementStatus(tmp_path)
    control = service.control
    control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    control.register_suite("local", suite_file(tmp_path))
    control.save(
        "local",
        {
            **control.preferences("local"),
            "suite_id": "data",
            "machine_ids": ["a"],
            "daily_episodes": 2,
        },
    )
    service.runs.configure("local", {**service.runs.settings("local"), "daily_tokens": 2000000})
    for key in ["one", "two"]:
        enqueue_diagnostic(service, "local", {"request_key": key, "case_ids": ["a"]})
    enqueue_diagnostic(service, "local", {"request_key": "three", "case_ids": ["a"]})
    with service.ledger.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_budgets").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM rsi_pipeline_runs").fetchone()[0] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("output_limit", [None, 8192])
@pytest.mark.parametrize("shared", [True, False])
async def test_diagnostic_admission_evidence_matches_policy_and_keeps_model_output_limit(
    tmp_path, monkeypatch, output_limit, shared
):
    from dataclasses import replace

    from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
    from roami_agent.improvement.workflows.pipeline_runner import execute_diagnostic
    from roami_agent.protocol.model_routes import settings_with_route
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.server.configuration import Settings

    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = shared
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", suite_file(tmp_path))
    service.control.save(
        "local", {**service.control.preferences("local"), "suite_id": "data", "machine_ids": ["a"]}
    )
    settings = Settings()
    parameters = {} if output_limit is None else {"max_tokens": output_limit}
    settings = settings_with_route(
        settings, "main", replace(settings.route("main"), parameters=parameters)
    )
    received = []

    class Provider:
        model = "daily-limit-fixture"

        async def stream(self, messages, tools):
            received.append(messages)
            yield ModelEvent("text", "2")
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 10,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    service.provider_factory = lambda *args: Provider()

    class Executor(ContainerExecutor):
        async def preflight(self):
            return {"environment_hash": "a" * 64}

        async def run(self, case, policy, target):
            provider = self.provider_factory(settings, "main")
            events = [
                event async for event in provider.stream([{"role": "user", "content": "2"}], [])
            ]
            assert any(event.kind == "text" and event.value == "2" for event in events)
            return {
                "grade": {"passed": True, "hard_passed": True, "pending": False, "quality": 80},
                "metrics": self.shared_budget.metrics(),
            }

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.execution.containers.ContainerExecutor", Executor
    )
    run = enqueue_diagnostic(service, "local", {"request_key": "optional-cap", "case_ids": ["a"]})
    await execute_diagnostic(
        SimpleNamespace(settings=SimpleNamespace(current=settings)),
        service,
        service.control.claim(),
    )
    value = service.runs.get("local", run["id"])
    assert len(received) == 1 and value["cases"][0]["passed"]
    assert value["summary"]["generation_tokens"] == 11
    assert settings.route("main").parameters == parameters
    budgets = [
        json.loads(service.runs.read_artifact("local", run["id"], a["id"])["text"])
        for a in value["artifacts"]
        if a["name"].startswith("budget-") and a["name"] != "budget-plan.json"
    ]
    assert len(budgets) == 1
    evidence = budgets[0]
    original = evidence["original_limits"]
    assert all(type(original[key]) is int for key in ("seconds", "tokens", "requests"))
    assert evidence["effective_limits"]["seconds"] == original["seconds"]
    assert evidence["spending_policy"] == "shared_model_daily"
    assert evidence["effective_limits"]["tokens"] is None
    assert evidence["effective_limits"]["requests"] is None
    assert evidence["run_token_limit"] is None
    assert evidence["reserved_for_later_cases"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "paths",
    [
        ["one/report.md", "two/report.md"],
        ["方案.md", "notes.md"],
        ["long-" + "x" * 115 + ".md", "notes.md"],
    ],
)
async def test_diagnostic_archives_nested_unicode_and_long_output_names(
    tmp_path, monkeypatch, paths
):
    from roami_agent.improvement.workflows.pipeline_runner import execute_diagnostic
    from roami_agent.server.configuration import Settings

    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", suite_file(tmp_path))
    service.control.save(
        "local", {**service.control.preferences("local"), "suite_id": "data", "machine_ids": ["a"]}
    )
    contents = {name: "delivered-file:" + name for name in paths}

    class Executor:
        model_hash = "b" * 64

        def __init__(self, *args, **kwargs):
            pass

        async def preflight(self):
            return {"environment_hash": "a" * 64}

        async def run(self, case, policy, target):
            for name, content in contents.items():
                path = target / "workspace" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            return {"grade": {"passed": True}, "metrics": {"tokens": 0}}

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.execution.containers.ContainerExecutor", Executor
    )
    run = enqueue_diagnostic(service, "local", {"request_key": "archive", "case_ids": ["a"]})
    await execute_diagnostic(
        SimpleNamespace(settings=SimpleNamespace(current=Settings())),
        service,
        service.control.claim(),
    )
    value = service.runs.get("local", run["id"])
    archived = [
        service.runs.read_artifact("local", run["id"], artifact["id"])
        for artifact in value["artifacts"]
    ]
    deliveries = [artifact for artifact in archived if artifact["text"] in contents.values()]
    assert {artifact["text"] for artifact in deliveries} == set(contents.values())
    assert len({artifact["name"] for artifact in deliveries}) == len(paths)
    assert all(
        artifact["name"].isascii() and len(artifact["name"]) <= 120 for artifact in deliveries
    )
    assert value["cases"][0]["passed"] and value["summary"]["cases"] == 1
