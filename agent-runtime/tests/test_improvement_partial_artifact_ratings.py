"""Completed blind ratings survive a later interruption without becoming a task pass."""

import asyncio
import copy
import json
from pathlib import Path

import pytest
from test_improvement_artifact_review import pack, reviewer

from roami_agent.improvement.evaluation import artifact_review
from roami_agent.improvement.evaluation.artifact_review_receipts import recorded_review
from roami_agent.improvement.evaluation.execution.executors import ProtocolFixtureModel
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent

DATA = json.loads((Path(__file__).parent / "fixtures/partial-artifact-ratings.json").read_text())


@pytest.fixture(autouse=True)
def rendered_evidence(monkeypatch):
    async def evidence(case, grade, root, executor):
        workspace = root / "workspace"
        workspace.mkdir(exist_ok=True)
        (workspace / "plan.md").write_bytes(b"A concrete plan")
        return pack()

    monkeypatch.setattr(artifact_review, "collect_artifact_evidence", evidence)


def original_grade():
    return {
        "hard_passed": True,
        "pending": True,
        "passed": False,
        "quality": 0,
        "checks": {"native": True},
        "native_partial": {"unscored_points": DATA["original_native_unscored_points"]},
    }


def scripted(mode, calls, *, second_started=None):
    class Model(ProtocolFixtureModel):
        def __init__(self, role):
            super().__init__([{"text": json.dumps(DATA["first_rating"])}])
            self.role = role

        async def stream(self, messages, tools):
            calls.append((self.role, copy.deepcopy(messages)))
            await asyncio.sleep(0)
            if self.role == "worker":
                if second_started:
                    second_started.set()
                if mode == "model_503":
                    raise DomainError("MODEL_HTTP_503")
                if mode in {"timeout", "cancel"}:
                    await asyncio.Event().wait()
                if mode == "output_limit":
                    yield ModelEvent("text", "x" * 16001)
                    return
                if mode == "bad_json":
                    self.script = [{"text": DATA["second_invalid_text"]}]
            async for event in super().stream(messages, tools):
                yield event

        async def close(self):
            if mode == "close_main" and self.role == "main":
                raise DomainError("FIXTURE_PROVIDER_CLOSE_FAILED")

    return reviewer(lambda settings, role: Model(role))


@pytest.mark.parametrize("mode", ["bad_json", "model_503", "output_limit", "close_main"])
async def test_completed_first_rating_survives_later_failure(tmp_path, mode):
    calls = []
    judge = scripted(mode, calls)
    budget = judge.budget()
    journal = []
    original = original_grade()
    result = await judge.review(
        {"grading_profile": "presentation"},
        original,
        tmp_path,
        None,
        budget=budget,
        journal=journal,
    )
    receipt = json.loads((tmp_path / "artifact-review.json").read_text())
    assert receipt["completed_raters"] == 1 and receipt["expected_raters"] == 2
    assert len(receipt["ratings"]) == 1 and receipt["ratings"][0]["rater"] == "artifact_a"
    assert receipt["ratings"][0]["dimensions"] == DATA["first_rating"]["dimensions"]
    assert len(calls) == (1 if mode == "close_main" else 2) == len(journal)
    assert result["pending"] and not result["passed"] and result["quality"] == 0
    assert (
        result["checks"] == original["checks"]
        and result["native_partial"] == original["native_partial"]
    )
    summary = trial_summary(
        {"id": "fixture-partial"}, {"grade": result, "metrics": budget.metrics()}, tmp_path
    )
    assert summary["artifact_review"]["completed_raters"] == 1 and not summary["passed"]
    assert summary["metrics"]["tokens"] == budget.metrics()["tokens"]
    assert "Synthetic visible observation" not in json.dumps(summary["artifact_review"])


async def test_timeout_keeps_first_rating_and_pending_state(tmp_path):
    calls = []
    judge = scripted("timeout", calls)
    judge.profile["seconds"] = 0.2
    result = await judge.review(
        {"grading_profile": "presentation"},
        original_grade(),
        tmp_path,
        None,
        budget=judge.budget(),
        journal=[],
    )
    assert result["pending"] and not result["passed"] and len(calls) == 2
    assert json.loads((tmp_path / "artifact-review.json").read_text())["completed_raters"] == 1


async def test_cancellation_keeps_partial_receipt_and_propagates(tmp_path):
    calls = []
    started = asyncio.Event()
    judge = scripted("cancel", calls, second_started=started)
    task = asyncio.create_task(
        judge.review(
            {"grading_profile": "presentation"},
            original_grade(),
            tmp_path,
            None,
            budget=judge.budget(),
            journal=[],
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    receipt = json.loads((tmp_path / "artifact-review.json").read_text())
    assert receipt["completed_raters"] == 1
    assert receipt["error"] == "RSI_ARTIFACT_REVIEW_INTERRUPTED" and len(calls) == 2


async def test_successful_blind_review_keeps_both_scores_and_separate_messages(tmp_path):
    calls = []
    judge = scripted("complete", calls)
    result = await judge.review(
        {"grading_profile": "presentation"},
        original_grade(),
        tmp_path,
        None,
        budget=judge.budget(),
        journal=[],
    )
    assert (
        result["passed"]
        and not result["pending"]
        and result["artifact_review"]["completed_raters"] == 2
    )
    assert result["artifact_review"]["error"] is None and calls[0][1] == calls[1][1]
    assert "Synthetic visible observation" not in json.dumps(calls[1][1])


async def test_caller_cannot_seed_a_collector_to_skip_a_rater():
    calls = []
    judge = scripted("complete", calls)
    with pytest.raises(DomainError, match="RSI_ARTIFACT_REVIEW_REQUIRED"):
        await judge.rate(pack(), judge.budget(), [], ratings=[{"rater": "forged"}])
    assert not calls


async def test_same_reviewer_parallel_runs_keep_independent_partial_lists(tmp_path):
    calls = []
    judge = scripted("bad_json", calls)
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()
    results = await asyncio.gather(
        *(
            judge.review(
                {"grading_profile": "presentation"},
                original_grade(),
                root,
                None,
                budget=judge.budget(),
                journal=[],
            )
            for root in roots
        )
    )
    assert all(r["artifact_review"]["completed_raters"] == 1 and not r["passed"] for r in results)
    assert len(calls) == 4


def test_legacy_case_without_a_review_does_not_get_a_fake_counter():
    value = trial_summary({"id": "no-review"}, {"grade": {"passed": False}, "metrics": {}})
    assert "artifact_review" not in value


def test_recovery_reads_partial_receipt_without_promoting_the_case(tmp_path):
    receipt = {
        "schema_version": 1,
        "ratings": [{"rater": "artifact_a", "blind": True, **DATA["first_rating"]}],
        "error": "RSI_ARTIFACT_REVIEW_INTERRUPTED",
        "evidence_hash": pack()["content_hash"],
        "completed_raters": 1,
        "expected_raters": 2,
    }
    (tmp_path / "artifact-review.json").write_text(json.dumps(receipt))
    result = {
        "grade": {"passed": False, "reason": "RSI_JOB_INTERRUPTED"},
        "metrics": {"tokens": None, "token_coverage": "unknown"},
    }
    summary = trial_summary({"id": "recovered"}, result, tmp_path)
    assert summary["artifact_review"]["completed_raters"] == 1 and not summary["passed"]
    assert (
        summary["metrics"]["tokens"] is None
        and "evidence" not in summary["artifact_review"]["scores"][0]
    )


@pytest.mark.parametrize("fault", ["dimensions_list", "symlink"])
def test_malformed_or_symlink_receipts_remain_unknown(tmp_path, fault):
    path = tmp_path / "artifact-review.json"
    if fault == "dimensions_list":
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "ratings": [
                        {
                            "rater": "artifact_a",
                            "blind": True,
                            "dimensions": list(DATA["first_rating"]["dimensions"]),
                        }
                    ],
                }
            )
        )
    else:
        target = tmp_path.parent / "external-review.json"
        target.write_text("{}")
        path.symlink_to(target)
    assert recorded_review(tmp_path) is None
