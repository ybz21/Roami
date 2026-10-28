import asyncio
import copy
import json

import pytest

from roami_agent.improvement.evaluation.behavior_review import review_cycle, review_trial
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.workflows.cycle import run_cycle
from roami_agent.protocol.errors import DomainError


class RegressionExecutor:
    model_hash = "a" * 64

    def __init__(self, *, cancel_after=None, reservation=0):
        self.calls, self.cancel_after, self.reservation = 0, cancel_after, reservation

    def reservation_tokens(self, case):
        return self.reservation

    async def run(self, case, policy, root):
        if self.cancel_after == self.calls:
            raise asyncio.CancelledError
        self.calls += 1
        (root / "regression.log").write_text("test_invariant PASSED\n1 passed\n")
        return {
            "execution_kind": "runtime_regression_variant",
            "grade": {"passed": True, "quality": 80, "pending": False},
            "metrics": {"tokens": 0, "elapsed_ms": 1, "model_calls": 0},
            "verified_delivery": False,
            "release_blockers": [],
        }


def cycle_arguments(tmp_path, executor):
    suite = freeze_suite(
        "sixty",
        [
            {
                "id": f"C{i}",
                "category": "HARNESS",
                "layer": "smoke",
                "split": "development",
                "prompt": "Check a deterministic invariant.",
                "counts_as_delivery": False,
                "files": {},
                "judge": {"kind": "numeric", "expected": 1},
                "limits": {"seconds": 10, "tokens": 10000, "requests": 2},
            }
            for i in range(60)
        ],
    )
    return {
        "ledger": Ledger(tmp_path / "ledger.sqlite3"),
        "owner": "local",
        "day": "2026-10-23",
        "suite": suite,
        "machine": {"id": "a", "cache_mode": "cold", "environment_hash": "a" * 64},
        "executor": executor,
        "baseline": {},
        "candidate": {},
        "output_root": tmp_path / "runs",
        "daily_tokens": 1,
        "daily_episodes": 120,
    }


async def test_all_sixty_cases_and_every_log_are_reviewed_without_paid_model_calls(tmp_path):
    executor = RegressionExecutor()
    arguments = cycle_arguments(tmp_path, executor)
    result = await run_cycle(**arguments)
    assert executor.calls == 120
    assert result["coverage"] == {
        "expected_cases": 60,
        "executed_cases": {"baseline": 60, "candidate": 60},
        "execution_complete": True,
    }
    assert result["full_suite_complete"] and not result["daily_complete"]
    assert result["review"]["metrics_reviewed"] == result["review"]["logs_reviewed"] == 120
    assert result["review"]["review_model_tokens"] == 0
    review = json.loads((arguments["output_root"] / result["cycle_id"] / "review.json").read_text())
    assert len(review["trials"]) == 120
    assert all(
        t["logs"][0]["sha256"] and t["logs"][0]["lines_reviewed"] == 2 for t in review["trials"]
    )
    assert not (await run_cycle(**arguments))["admitted"]
    assert executor.calls == 120


@pytest.mark.parametrize(
    "change,code",
    [
        ({"daily_episodes": 118}, "FULL_SUITE_BUDGET"),
        ({"daily_tokens": 11999}, "FULL_SUITE_BUDGET"),
        ({"case_limit": 4}, "FULL_SUITE_REQUIRED"),
    ],
)
async def test_partial_budget_or_old_sample_limit_cannot_silently_shrink_daily_suite(
    tmp_path, change, code
):
    executor = RegressionExecutor(reservation=100)
    arguments = {**cycle_arguments(tmp_path, executor), "daily_tokens": 12000, **change}
    with pytest.raises(DomainError, match=code):
        await run_cycle(**arguments)
    assert executor.calls == 0 and arguments["ledger"].list("local") == []


async def test_interruption_preserves_partial_review_and_never_claims_daily_completion(tmp_path):
    arguments = cycle_arguments(tmp_path, RegressionExecutor(cancel_after=1))
    with pytest.raises(asyncio.CancelledError):
        await run_cycle(**arguments)
    cycle = arguments["ledger"].list("local")[0]
    assert cycle["state"] == "interrupted" and not cycle["report"]["daily_complete"]
    assert cycle["report"]["review"]["metrics_reviewed"] == 1
    assert not cycle["report"]["coverage"]["execution_complete"]
    assert (arguments["output_root"] / cycle["id"] / "interrupted-review.json").is_file()


def trial_record():
    return {
        "case_id": "x",
        "split": "development",
        "execution_kind": "native_files",
        "grade": {"passed": True, "quality": 80},
        "verified_delivery": True,
        "metrics": {"tokens": 100, "model_calls": 1, "retries": 1, "elapsed_ms": 10},
    }


def logs(root):
    record = {
        "role": "main",
        "messages": [{"role": "user", "content": "private task"}],
        "tools": [],
        "events": [{"kind": "text", "value": "Done"}],
        "measurement": {"inputTokens": 80, "outputTokens": 20},
    }
    private_json(root / "model-log.json", {"requests": [record]})
    tools = [
        {
            "id": str(i),
            "tool_name": "read",
            "state": "succeeded",
            "arguments_json": '{"path":"input.json"}',
            "result_json": '"same version"',
        }
        for i in range(2)
    ]
    tools.append({"id": "write", "tool_name": "write", "state": "unknown", "arguments_json": "{}"})
    private_json(
        root / "execution-log.json",
        {
            "tool_calls": tools,
            "traces": [
                {
                    "spans": [
                        {
                            "spanId": "s1",
                            "name": "tool.read",
                            "durationMs": 12,
                            "state": "succeeded",
                        }
                    ]
                }
            ],
        },
    )


def test_successful_trials_are_also_reviewed_against_concrete_calls_and_evidence(tmp_path):
    logs(tmp_path)
    record = trial_record()
    reviewed = review_trial(record, tmp_path)
    assert reviewed["complete"] and reviewed["model_requests_reviewed"] == 1
    assert reviewed["tool_records_reviewed"] == 3
    findings = {f["code"]: f for f in reviewed["findings"]}
    assert {"repeated_read", "unknown_tool_outcome", "request_retries"} <= findings.keys()
    assert len(findings["repeated_read"]["evidence"]) == 2
    assert "不要直接重试" in findings["unknown_tool_outcome"]["suggestion"]
    assert reviewed["slowest_spans"][0]["evidence"]["span_id"] == "s1"
    assert record == trial_record()


@pytest.mark.parametrize("failure", ["missing", "malformed", "escape"])
def test_unreadable_logs_cannot_be_counted_as_complete_review(tmp_path, failure):
    if failure == "malformed":
        (tmp_path / "model-log.json").write_text("{broken")
    elif failure == "escape":
        (tmp_path / "model-log.json").symlink_to("/etc/passwd")
    reviewed = review_trial(trial_record(), tmp_path)
    assert not reviewed["complete"]
    assert "log_unavailable" in {f["code"] for f in reviewed["findings"]}
    assert all("root:" not in json.dumps(f) for f in reviewed["findings"])


def test_review_includes_failure_costs_unknown_usage_and_paired_regressions(tmp_path):
    logs(tmp_path)
    a = trial_record()
    a["log_review"] = review_trial(a, tmp_path)
    b = copy.deepcopy(a)
    b["metrics"].update(tokens=200, elapsed_ms=20)
    b["log_review"] = review_trial(b, tmp_path)
    result = review_cycle({"case_ids": ["x"]}, {"baseline": [a], "candidate": [b]})
    assert {f["code"] for f in result["pair_findings"]} == {"token_regression", "time_regression"}
    failed = copy.deepcopy(b)
    failed.update(case_id="failed", verified_delivery=False)
    failed["grade"].update(passed=False, quality=0)
    result = review_cycle(
        {"case_ids": ["x", "failed"]}, {"baseline": [a], "candidate": [b, failed]}
    )
    assert result["summary"]["cost"]["candidate"]["tokens_per_pass_including_failures"] == 400
    failed["metrics"]["tokens"] = None
    result = review_cycle(
        {"case_ids": ["x", "failed"]}, {"baseline": [a], "candidate": [b, failed]}
    )
    assert result["summary"]["cost"]["candidate"]["total_tokens_including_failures"] is None
    assert not result["summary"]["complete"]


async def test_external_worker_log_limit_preserves_bounded_output_and_does_not_hang(tmp_path):
    import sys

    from roami_agent.improvement.evaluation.execution.executors import ExternalExecutor

    program = tmp_path / "noisy.py"
    program.write_text("import sys\nsys.stdout.write('x' * 5000000)\nsys.stdout.flush()\n")
    root = tmp_path / "trial"
    root.mkdir()
    case = cycle_arguments(tmp_path, RegressionExecutor())["suite"]["cases"][0]
    executor = ExternalExecutor([sys.executable, str(program)], model_hash="a" * 64)
    with pytest.raises(DomainError, match="LOG_TOO_LARGE"):
        await asyncio.wait_for(executor.run(case, {}, root), timeout=5)
    assert 0 < (root / "worker-stdout.log").stat().st_size <= 4_000_000


async def test_single_baseline_keeps_every_case_and_log_without_duplicate_trials(tmp_path):
    executor = RegressionExecutor(reservation=10)
    arguments = {
        **cycle_arguments(tmp_path, executor),
        "daily_tokens": 600,
        "daily_episodes": 60,
        "paired": False,
    }
    result = await run_cycle(**arguments)
    assert executor.calls == 60
    assert result["full_suite_complete"] and result["review"]["expected_trials"] == 60
    assert result["review"]["logs_reviewed"] == result["review"]["metrics_reviewed"] == 60
    assert set(result["counts"]) == {"baseline"}
    assert result["comparison"]["pairs"] == 0 and not result["comparison"]["eligible_for_promotion"]
    cycle = arguments["ledger"].get("local", result["cycle_id"])
    assert cycle["manifest"]["trial_arms"] == ["baseline"]
    assert cycle["manifest"]["reserved_tokens"] == 600
    assert cycle["manifest"]["reserved_episodes"] == 60
    assert not (await run_cycle(**arguments))["admitted"] and executor.calls == 60


async def test_changed_policy_cannot_skip_its_paired_comparison(tmp_path):
    executor = RegressionExecutor()
    with pytest.raises(DomainError, match="COMPARISON_REQUIRED"):
        await run_cycle(
            **{
                **cycle_arguments(tmp_path, executor),
                "paired": False,
                "candidate": {"memory_recall_tokens": 1500},
            }
        )
    assert executor.calls == 0
