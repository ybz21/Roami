import json
from types import SimpleNamespace

import pytest
from test_improvement_control import suite_file

from roami_agent.improvement.github_publication import configure_publication
from roami_agent.improvement.pipeline_reports import RunCosts, publish_run_issue
from roami_agent.improvement.pipeline_runner import enqueue_diagnostic
from roami_agent.improvement.run_records import trial_summary
from roami_agent.improvement.status import ImprovementStatus
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
    with pytest.raises(DomainError, match="DAILY_BUDGET"):
        enqueue_diagnostic(service, "local", {"request_key": "three", "case_ids": ["a"]})
    with service.ledger.connection() as db:
        assert db.execute("SELECT tokens_reserved FROM rsi_budgets").fetchone()[0] == 856000
        assert db.execute("SELECT COUNT(*) FROM rsi_pipeline_runs").fetchone()[0] == 2
    service.runs.configure("local", {**service.runs.settings("local"), "daily_tokens": 2000000})
    enqueue_diagnostic(service, "local", {"request_key": "three", "case_ids": ["a"]})
    with pytest.raises(DomainError, match="DAILY_BUDGET"):
        service.runs.configure("local", {**service.runs.settings("local"), "daily_tokens": 1000000})


def test_unknown_codex_cost_prevents_paid_replay(tmp_path):
    service, run_id = setup_run(tmp_path)
    costs = RunCosts(service.runs, "local", run_id)
    assert costs.reserve_operation("local", "today", "first", 64000) is None
    with pytest.raises(DomainError, match="RECONCILIATION"):
        costs.reserve_operation("local", "today", "first", 64000)
    with pytest.raises(DomainError, match="RECONCILIATION"):
        costs.reserve_operation("local", "today", "second", 64000)
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
    service.runs.capture_request({"owner": "local", "id": run_id})
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
    service.runs.freeze_cases("local", run_id, suite)
    assert service.runs.get("local", run_id)["snapshot"]["case_ids"] == ["a", "b"]
    with pytest.raises(DomainError, match="CASES_CHANGED"):
        service.runs.freeze_cases("local", run_id, {**suite, "cases": [{"id": "b"}]})
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
