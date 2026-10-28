import copy
import json

import pytest
from test_improvement import case, trial

from roami_agent.improvement.domain.comparison import compare
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.service import ImprovementStatus
from roami_agent.improvement.workflows.cycle import run_cycle


class RefusingExecutor:
    model_hash = "b" * 64

    def __init__(self, reason, generic=False):
        self.reason, self.calls = reason, []
        self.generic = generic

    def reservation_tokens(self, case):
        return 0

    async def run(self, case, policy, root):
        self.calls.append(case["id"])
        mechanism = case["judge"]["kind"] == "mechanism"
        unknown = self.reason == "RSI_USAGE_UNKNOWN" and not mechanism
        if mechanism:
            (root / "regression.log").write_text("mechanism fixture passed\n")
        else:
            (root / "state").mkdir()
            (root / "state/execution-log.json").write_text(
                json.dumps({"tool_calls": [], "traces": []})
            )
            (root / "model-log.json").write_text(
                json.dumps(
                    {
                        "requests": [
                            {
                                "role": "memory",
                                "messages": [],
                                "tools": [],
                                "events": [],
                                "measurement": {
                                    "inputTokens": None if unknown else 0,
                                    "outputTokens": None if unknown else 0,
                                },
                                "error_code": self.reason,
                            }
                        ]
                    }
                )
            )
        return {
            "grade": {
                "passed": mechanism,
                "hard_passed": mechanism,
                "pending": False,
                "quality": 80 if mechanism else 0,
                "reason": "assertions_passed"
                if mechanism
                else "RSI_GATEWAY_FAILED"
                if self.generic
                else self.reason,
            },
            "metrics": {
                "tokens": None if unknown else 0,
                "token_coverage": "unknown" if unknown else "complete",
                "model_calls": 0 if mechanism else 1,
                "tool_calls": 0,
                "elapsed_ms": 1,
            },
            "execution_kind": "runtime_regression_variant"
            if mechanism
            else "isolated_native_worker",
            "verified_delivery": False,
            "release_blockers": ["unknown_provider_usage"] if unknown else [],
            "blocked_by": {"case_id": "forged", "code": "MODEL_PROXY_DAILY_LIMIT"},
        }


def suite():
    return freeze_suite(
        "admission",
        [
            case("REAL-A"),
            case("REAL-B"),
            case(
                "MECH-SK02",
                layer="mechanism",
                judge={"kind": "mechanism"},
                counts_as_delivery=False,
            ),
        ],
    )


def arguments(ledger, executor, output_root, *, paired=True, request_key="one"):
    return {
        "ledger": ledger,
        "owner": "local",
        "day": "2026-10-28",
        "suite": suite(),
        "machine": {"id": "container", "cache_mode": "cold", "environment_hash": "a" * 64},
        "executor": executor,
        "baseline": {},
        "candidate": {},
        "output_root": output_root,
        "daily_tokens": 1,
        "daily_episodes": 10,
        "paired": paired,
        "request_key": request_key,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("generic", [False, True])
@pytest.mark.parametrize("paired", [False, True])
@pytest.mark.parametrize(
    "reason", ["RSI_USAGE_UNKNOWN", "MODEL_PROXY_USAGE_UNKNOWN", "MODEL_PROXY_DAILY_LIMIT"]
)
async def test_formal_cycle_stops_after_shared_blocker_and_keeps_mechanisms(
    tmp_path, reason, paired, generic
):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.shared_daily_limit = True
    executor = RefusingExecutor(reason, generic)
    params = arguments(ledger, executor, tmp_path / "runs", paired=paired)
    report = await run_cycle(**params)
    arms = 2 if paired else 1
    assert len([c for c in executor.calls if c.startswith("REAL-")]) == 1
    assert executor.calls.count("MECH-SK02") == arms
    detail = ledger.get("local", report["cycle_id"])
    source = next(
        t for t in detail["trials"] if t["case_id"].startswith("REAL-") and not t.get("blocked_by")
    )
    assert report["usage_blocker"] == {
        "case_id": source["case_id"],
        "arm": source["arm"],
        "code": reason,
    }
    inherited = [t for t in detail["trials"] if t.get("blocked_by")]
    assert len(inherited) == 2 * arms - 1
    for t in inherited:
        assert t["blocked_by"] == report["usage_blocker"]
        assert t["metrics"]["tokens"] == t["metrics"]["model_calls"] == 0
        assert not t["grade"]["passed"] and not t["verified_delivery"]
        assert t["log_review"]["complete"]
        assert {f["code"] for f in t["log_review"]["findings"]} == {"admission_blocked"}
    assert not report["full_suite_complete"] and not report["evaluation_complete"]
    assert not report["comparison"]["eligible_for_promotion"]
    before = list(executor.calls)
    assert not (await run_cycle(**params))["admitted"]
    assert executor.calls == before


@pytest.mark.parametrize("inherited", [False, True])
def test_admission_blocked_pair_is_unverified_not_a_quality_regression(inherited):
    before = trial("a")
    after = copy.deepcopy(before)
    after.update(
        grade={"passed": False, "quality": 0, "reason": "MODEL_PROXY_USAGE_UNKNOWN"},
        verified_delivery=False,
    )
    if inherited:
        after["blocked_by"] = {
            "case_id": "earlier",
            "arm": "baseline",
            "code": "MODEL_PROXY_USAGE_UNKNOWN",
        }
    result = compare([before], [after])
    assert result["baseline_pass_regressions"] == []
    assert result["quality_delta"] is None
    assert result["pairs"] == 0 and result["admission_blocked_cases"] == ["a"]
    assert "admission_blocked_pairs" in result["reasons"]
    assert not result["eligible_for_promotion"]


@pytest.mark.asyncio
async def test_formal_capture_keeps_primary_arm_and_free_summary(tmp_path):
    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite()))
    service.control.register_machine(
        "local", {"id": "container", "label": "Container", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", path)
    service.control.save(
        "local",
        {
            **service.control.preferences("local"),
            "suite_id": "admission",
            "machine_ids": ["container"],
        },
    )
    service.control.enqueue("local", machine_id="container", request_key="formal")
    request = service.control.claim()
    service.run_lifecycle.begin_request(request)
    service.run_lifecycle.freeze_cases("local", request["id"], suite())
    executor = RefusingExecutor("RSI_USAGE_UNKNOWN")
    report = await run_cycle(
        **arguments(service.ledger, executor, tmp_path / "runs", request_key=request["id"])
    )
    service.control.finish(
        request, "blocked", cycle_id=report["cycle_id"], error_code="RSI_REVIEW_INCOMPLETE"
    )
    service.run_lifecycle.capture_request(request)
    run = service.runs.get("local", request["id"])
    assert run["summary"]["generation_tokens"] is None
    assert run["summary"]["usage_blocker"] == report["usage_blocker"]
    source = next(c for c in run["cases"] if c["case_id"] == report["usage_blocker"]["case_id"])
    assert source["arm"] == report["usage_blocker"]["arm"] and not source.get("blocked_by")
    assert len(source["arm_results"]) == 2
    assert all(i["case_id"] == source["case_id"] for i in run["issues"])
    artifact = next(a for a in run["artifacts"] if a["name"] == "evaluation-summary.md")
    text = service.runs.read_artifact("local", run["id"], artifact["id"])["text"]
    assert "Codex 复盘与独立验收以对应环节的回执为准" in text
    assert report["usage_blocker"]["case_id"] in text
    assert "baseline" in text and "candidate" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("refused", [False, True])
async def test_formal_usage_gaps_defer_admission_to_the_shared_fee_policy(tmp_path, refused):
    from roami_agent.protocol.errors import DomainError

    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.shared_daily_limit = True
    executor = RefusingExecutor("RSI_USAGE_UNKNOWN")
    checks = []

    async def check():
        checks.append(True)
        if refused:
            raise DomainError("MODEL_PROXY_USAGE_UNKNOWN")

    params = arguments(ledger, executor, tmp_path / "runs")
    report = await run_cycle(**params, admission_check=check)
    real = [c for c in executor.calls if c.startswith("REAL-")]
    assert len(real) == (1 if refused else 4)
    assert len(checks) == len(real)
    assert bool(report["usage_blocker"]) is refused
    assert not report["evaluation_complete"] and not report["comparison"]["eligible_for_promotion"]
    detail = ledger.get("local", report["cycle_id"])
    for t in detail["trials"]:
        if t["case_id"].startswith("REAL-") and not t.get("blocked_by"):
            assert t["metrics"]["tokens"] is None
            assert bool(t.get("shared_admission_checked")) is not refused
    if refused:
        assert report["usage_blocker"]["code"] == "MODEL_PROXY_USAGE_UNKNOWN"


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        ([], (None, None, None, 0)),
        ([{"tokens": 13, "artifact_review_tokens": 3}], (13, 10, 3, 13)),
        ([{"tokens": None, "observed_tokens": 7}], (None, None, 0, 7)),
        ([{"tokens": None, "artifact_review_tokens": None}], (None, None, None, 0)),
        ([{"tokens": True}], (None, None, 0, 0)),
    ],
)
def test_formal_usage_never_turns_missing_measurement_into_free_tokens(metrics, expected):
    from roami_agent.improvement.evaluation.trial_evidence import cycle_usage

    actual = cycle_usage([{"metrics": m} for m in metrics])
    assert (
        tuple(
            actual[k]
            for k in (
                "evaluation_tokens",
                "generation_tokens",
                "artifact_review_tokens",
                "known_evaluation_tokens",
            )
        )
        == expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("prices", [False, True])
async def test_diagnostic_usage_gaps_follow_actual_shared_billing(
    store, tmp_path, monkeypatch, prices
):
    from types import SimpleNamespace

    import httpx
    from test_model_proxy import consume, provider, proxy_for

    from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
    from roami_agent.improvement.persistence.run_costs import RunCosts
    from roami_agent.improvement.workflows.pipeline_runner import (
        enqueue_diagnostic,
        execute_diagnostic,
    )
    from roami_agent.protocol.errors import DomainError
    from roami_agent.server.configuration import Settings

    proxy, _ = proxy_for(store, limit=1, prices=prices)
    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    service.model_proxy = service.runs.model_proxy = proxy
    calls, executed = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"done"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    service.provider_factory = lambda settings, role: provider(proxy, handler, role)
    path = tmp_path / "two.json"
    path.write_text(json.dumps(freeze_suite("two", [case("a"), case("b")])))
    service.control.register_machine(
        "local", {"id": "container", "label": "Container", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", path)
    service.control.save(
        "local",
        {**service.control.preferences("local"), "suite_id": "two", "machine_ids": ["container"]},
    )
    settings = Settings()

    class Executor(ContainerExecutor):
        async def preflight(self):
            return {"environment_hash": "a" * 64}

        async def run(self, case, policy, root):
            executed.append(case["id"])
            model = self.provider_factory(settings, "main")
            try:
                await consume(model)
            finally:
                await model.close()
            return {"grade": {"passed": True}, "metrics": self.shared_budget.metrics()}

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.execution.containers.ContainerExecutor", Executor
    )
    queued = enqueue_diagnostic(
        service, "local", {"request_key": "shared-fees", "case_ids": ["a", "b"]}
    )
    await execute_diagnostic(
        SimpleNamespace(settings=SimpleNamespace(current=settings)),
        service,
        service.control.claim(),
    )
    run = service.runs.get("local", queued["id"])
    assert len(calls) == len(executed) == (1 if prices else 2)
    assert run["summary"]["generation_tokens"] is None
    assert run["summary"]["passed"] == 0
    assert bool(run["summary"]["usage_blocker"]) is prices
    usage = await proxy.billing.daily_summary()
    assert usage["unknown"] == (1 if prices else 0)
    if not prices:
        await proxy.billing.check()
        costs = RunCosts(service.runs, "local", run["id"])
        assert costs.reserve_operation("local", "today", "review", 64000) is None
    else:
        with pytest.raises(DomainError, match="MODEL_PROXY_USAGE_UNKNOWN"):
            await proxy.billing.check()


def test_formal_unknown_usage_without_shared_billing_still_blocks_review(tmp_path):
    from roami_agent.improvement.persistence.run_costs import RunCosts
    from roami_agent.protocol.errors import DomainError

    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    ident = service.runs.create(
        "local", "unknown", "daily", {"pipeline": service.runs.settings("local")}
    )
    service.runs.set_state("local", ident, "report_queued", {"generation_tokens": None})
    with pytest.raises(DomainError, match="RSI_USAGE_UNKNOWN"):
        RunCosts(service.runs, "local", ident).reserve_operation("local", "today", "review", 64000)
