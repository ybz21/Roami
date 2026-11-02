"""Authentication outages stop a batch without manufacturing quality regressions."""

import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from test_improvement import case, trial
from test_improvement_admission_cycle import RefusingExecutor, arguments

from roami_agent.improvement.domain.comparison import compare
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.model_gateway import ModelGateway
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.presentation.run_results import results_view
from roami_agent.improvement.service import ImprovementStatus
from roami_agent.improvement.workflows.cycle import run_cycle
from roami_agent.improvement.workflows.pipeline_reports import PipelineReportWorker
from roami_agent.improvement.workflows.pipeline_runner import enqueue_diagnostic, execute_diagnostic
from roami_agent.protocol.errors import DomainError, ModelAdmissionRejected
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize("code", ["MODEL_HTTP_401", "MODEL_HTTP_403"])
@pytest.mark.parametrize("generic", [False, True])
@pytest.mark.parametrize("paired", [False, True])
async def test_formal_auth_failure_stops_later_real_cases(tmp_path, code, generic, paired):
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.shared_daily_limit = True
    executor = RefusingExecutor(code, generic)
    report = await run_cycle(**arguments(ledger, executor, tmp_path / "runs", paired=paired))
    assert len([c for c in executor.calls if c.startswith("REAL-")]) == 1
    assert executor.calls.count("MECH-SK02") == (2 if paired else 1)
    assert report["usage_blocker"]["code"] == code
    assert not report["evaluation_complete"] and not report["full_suite_complete"]
    assert not report["comparison"]["eligible_for_promotion"]
    saved = ledger.get("local", report["cycle_id"])
    for item in saved["trials"]:
        if item.get("blocked_by"):
            assert item["blocked_by"] == report["usage_blocker"]
            assert item["metrics"]["tokens"] == item["metrics"]["model_calls"] == 0


@pytest.mark.parametrize("code", ["MODEL_HTTP_401", "MODEL_HTTP_403"])
def test_auth_failure_is_not_a_scored_quality_regression(code):
    before = trial("a")
    after = copy.deepcopy(before)
    after.update(grade={"passed": False, "quality": 0, "reason": code}, verified_delivery=False)
    result = compare([before], [after])
    assert result["quality_delta"] is None and result["pairs"] == 0
    assert result["baseline_pass_regressions"] == []
    assert result["admission_blocked_cases"] == ["a"]


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("has_usage", [False, True])
async def test_diagnostic_auth_failure_keeps_usage_and_one_root_issue(
    tmp_path, monkeypatch, status, has_usage
):
    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    settings, called, requests = Settings(), [], []
    code = f"MODEL_HTTP_{status}"

    def respond(request):
        requests.append(True)
        if not has_usage:
            return httpx.Response(status)
        frames = [
            {"usage": {"prompt_tokens": 37, "completion_tokens": 5}},
            {"error": {"code": code}},
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(f) + "\n\n" for f in frames))

    service.provider_factory = lambda *args: ChatCompletions(
        "https://fixture.invalid/v1",
        "fixture",
        max_retries=2,
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )

    class Executor(ContainerExecutor):
        async def preflight(self):
            return {"environment_hash": "a" * 64}

        async def run(self, item, policy, root):
            called.append(item["id"])
            if item["judge"]["kind"] == "mechanism":
                return {"grade": {"passed": True}, "metrics": {"tokens": 0, "model_calls": 0}}
            provider = self.provider_factory(settings, "main")
            socket = tmp_path / "model.sock"
            async with ModelGateway(socket, {"main": provider}):
                child = ChatCompletions(
                    "http://localhost/v1/main",
                    "main",
                    max_retries=2,
                    client=httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket))),
                )
                try:
                    with pytest.raises(DomainError) as caught:
                        async for _ in child.stream([], []):
                            pass
                    assert caught.value.code == code
                    assert not isinstance(caught.value, ModelAdmissionRejected)
                finally:
                    await child.close()
                    await provider.close()
            return {
                "grade": {
                    "passed": False,
                    "quality": 0,
                    "reason": code,
                    "checks": {"artifact:updated.pptx": False},
                },
                "metrics": self.shared_budget.metrics(),
            }

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.execution.containers.ContainerExecutor", Executor
    )
    path = tmp_path / "suite.json"
    cases = [
        case("root"),
        case("later-a"),
        case("mechanism", judge={"kind": "mechanism"}),
        case("later-b"),
    ]
    path.write_text(json.dumps(freeze_suite("auth", cases)))
    service.control.register_machine(
        "local", {"id": "container", "label": "Container", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", path)
    service.control.save(
        "local",
        {**service.control.preferences("local"), "suite_id": "auth", "machine_ids": ["container"]},
    )
    receipt = enqueue_diagnostic(
        service, "local", {"request_key": "auth", "case_ids": [c["id"] for c in cases]}
    )
    await execute_diagnostic(
        SimpleNamespace(settings=SimpleNamespace(current=settings)),
        service,
        service.control.claim(),
    )
    value = service.runs.get("local", receipt["id"])
    assert called == ["root", "mechanism"] and len(requests) == 1
    assert value["summary"]["usage_blocker"] == {"case_id": "root", "code": code}
    assert value["summary"]["not_run"] == 2 and value["summary"]["blocked"] == 3
    assert value["summary"]["generation_tokens"] == (42 if has_usage else None)
    rows = {c["case_id"]: c for c in value["cases"]}
    assert rows["root"]["state"] == "blocked" and rows["root"]["quality"] is None
    assert rows["root"]["metrics"]["tokens"] == (42 if has_usage else None)
    assert "check:artifact:updated.pptx" in rows["root"]["signals"]
    assert [(i["case_id"], i["code"]) for i in value["issues"]] == [("root", code)]
    for ident in ["later-a", "later-b"]:
        assert rows[ident]["blocked_by"] == value["summary"]["usage_blocker"]
        assert rows[ident]["metrics"]["tokens"] == rows[ident]["metrics"]["model_calls"] == 0

    async def forbidden(*args, **kwargs):
        pytest.fail("Authentication blocker must prevent paid reports")

    monkeypatch.setattr("roami_agent.improvement.workflows.pipeline_reports.codex_json", forbidden)
    await PipelineReportWorker(service).execute(service.runs.claim_report())
    stopped = service.runs.get("local", value["id"])
    assert stopped["state"] == "blocked"
    assert next(n for n in stopped["nodes"] if n["node"] == "review")["error_code"] == code
    assert len(requests) == 1
    view = results_view(service.runs, "local", value["id"])
    run = view["runs"][0]
    assert run["state"] == "partial" and run["blocker"] == code
    assert view["issues"][0]["priority"] == "P1"
    artifact = next(a for a in value["artifacts"] if a["name"] == "evaluation-summary.md")
    text = service.runs.read_artifact("local", value["id"], artifact["id"])["text"]
    assert f"| `later-a` | `root` | `{code}` |" in text
    assert f"- [ ] P1 · `root` · `{code}`" in text


@pytest.mark.parametrize("code", ["MODEL_HTTP_401", "MODEL_HTTP_403"])
def test_recovered_auth_log_does_not_override_completed_grade(tmp_path, code):
    (tmp_path / "model-log.json").write_text(
        json.dumps({"requests": [{"role": "memory", "error_code": code}]})
    )
    summary = trial_summary(
        {"id": "a"}, {"grade": {"passed": True, "quality": 80}, "metrics": {"tokens": 10}}, tmp_path
    )
    assert summary["state"] == "passed" and summary["quality"] == 80
    records = ImprovementStatus(tmp_path / "db").runs
    run = records.create("local", "recovered", "diagnostic", {"case_ids": ["a"]})
    records.case("local", run, summary)
    records.node("local", run, "evaluate", "failed", code)
    records.node("local", run, "evaluate", "succeeded")
    view = results_view(records, "local", run)["runs"][0]
    assert view["blocker"] is None and view["results"]["a"] == "passed"


def test_real_quality_failure_keeps_actual_zero():
    summary = trial_summary(
        {"id": "a"}, {"grade": {"passed": False, "quality": 0, "reason": "native_failed"}}
    )
    assert summary["state"] == "failed" and summary["quality"] == 0


@pytest.mark.parametrize("code", ["MODEL_HTTP_401", "MODEL_HTTP_403"])
def test_auth_block_does_not_reproduce_or_close_older_artifact_failures(tmp_path, code):
    records = ImprovementStatus(tmp_path).runs
    before = records.create("local", "before", "diagnostic", {"case_ids": ["a"]})
    records.case(
        "local",
        before,
        trial_summary(
            {"id": "a"},
            {
                "grade": {
                    "passed": False,
                    "quality": 0,
                    "reason": "native_failed",
                    "checks": {"artifact:updated.pptx": False},
                },
                "metrics": {"tokens": 10},
            },
        ),
    )
    records.observations("local", before)
    older = {i["id"] for i in records.get("local", before)["issues"]}
    current = records.create("local", "current", "diagnostic", {"case_ids": ["a"]})
    records.case(
        "local",
        current,
        trial_summary(
            {"id": "a"},
            {
                "grade": {
                    "passed": False,
                    "quality": 0,
                    "reason": code,
                    "checks": {"artifact:updated.pptx": False},
                },
                "metrics": {"tokens": None},
            },
        ),
    )
    records.observations("local", current)
    issues = records.get("local", current)["issues"]
    assert len(issues) == len(older) + 1
    assert all(i["status"] == "unverified" for i in issues if i["id"] in older)
    assert [(i["code"], i["status"]) for i in issues if i["id"] not in older] == [(code, "present")]
