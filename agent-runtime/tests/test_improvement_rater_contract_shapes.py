"""Reject malformed rating objects without losing completed scores or known usage."""

import json
from pathlib import Path

import pytest
from test_improvement_artifact_review import (
    certificate,
    fixture_settings,
    pack,
    profile,
    rating,
    reviewer,
)

from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation import artifact_review
from roami_agent.improvement.evaluation.artifact_review_receipts import recorded_review
from roami_agent.improvement.evaluation.grading import calibrated_grade
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent

DATA = json.loads((Path(__file__).parent / "fixtures/rater-contract-shapes.json").read_text())


@pytest.fixture
def evidence(monkeypatch):
    async def collect(case, grade, root, executor):
        (root / "workspace").mkdir()
        (root / "workspace/plan.md").write_bytes(b"A concrete plan")
        return pack()

    monkeypatch.setattr(artifact_review, "collect_artifact_evidence", collect)


def scripted(bad_role, dimensions, calls, closed):
    class Model:
        model = "public-rating-contract-fixture"

        def __init__(self, role):
            self.role = role

        async def stream(self, messages, tools):
            calls.append(self.role)
            value = rating()
            if self.role == bad_role:
                value["dimensions"] = dimensions
            yield ModelEvent("text", json.dumps(value))
            yield ModelEvent("usage", dict(DATA["usage"]))

        async def close(self):
            closed.append(self.role)

    return reviewer(lambda settings, role: Model(role))


@pytest.mark.parametrize("dimensions", DATA["nonobjects"])
@pytest.mark.parametrize("bad_role", ["main", "worker"])
async def test_bad_dimensions_keep_review_pending_and_prior_rating(
    tmp_path, evidence, dimensions, bad_role
):
    calls, closed = [], []
    judge = scripted(bad_role, dimensions, calls, closed)
    budget, journal = judge.budget(), []
    original = {
        "hard_passed": True,
        "pending": True,
        "passed": False,
        "quality": 0,
        "checks": {"fixture": True},
        "native_partial": {"unscored_points": 7},
    }
    result = await judge.review(
        {"grading_profile": "presentation"},
        original,
        tmp_path,
        None,
        budget=budget,
        journal=journal,
    )
    count = 1 if bad_role == "main" else 2
    receipt = json.loads((tmp_path / "artifact-review.json").read_text())
    assert result["pending"] and not result["passed"] and result["quality"] == 0
    assert result["reason"] == receipt["error"] == "RSI_INVALID_CONTRACT"
    assert result["checks"] == original["checks"]
    assert result["native_partial"] == original["native_partial"]
    assert len(calls) == len(journal) == count and closed == calls
    assert receipt["completed_raters"] == count - 1
    assert receipt["metrics"]["tokens"] == budget.metrics()["tokens"] == 120 * count
    assert receipt["metrics"]["token_coverage"] == "complete"
    assert recorded_review(tmp_path) == result["artifact_review"]
    if bad_role == "worker":
        assert receipt["ratings"][0]["dimensions"] == rating()["dimensions"]


async def test_valid_object_ratings_still_complete_both_blind_raters(tmp_path, evidence):
    calls, closed = [], []
    judge = scripted(None, None, calls, closed)
    budget = judge.budget()
    result = await judge.review(
        {"grading_profile": "presentation"},
        {"hard_passed": True, "pending": True, "passed": False, "checks": {"fixture": True}},
        tmp_path,
        None,
        budget=budget,
        journal=[],
    )
    assert result["passed"] and not result["pending"]
    assert result["artifact_review"]["completed_raters"] == 2
    assert calls == closed == ["main", "worker"] and budget.metrics()["tokens"] == 240


def test_quality_rejects_a_dimension_name_array():
    with pytest.raises(DomainError, match="RSI_INVALID_CONTRACT"):
        quality(DATA["dimension_names"], hard_passed=True)


def test_calibrated_grade_rejects_a_dimension_name_array():
    ratings = [
        {"rater": name, "blind": True, "dimensions": DATA["dimension_names"]} for name in ["a", "b"]
    ]
    with pytest.raises(DomainError, match="RSI_INVALID_CONTRACT"):
        calibrated_grade({}, ratings, hard_passed=True, calibration_id="fixture")


@pytest.mark.parametrize("value", DATA["nonobjects"])
def test_calibrated_grade_rejects_nonobject_rater_records(value):
    with pytest.raises(DomainError, match="RSI_INVALID_CONTRACT"):
        calibrated_grade({}, [value, value], hard_passed=True, calibration_id="fixture")


@pytest.mark.parametrize(
    "fault", ["expected", "rating_dimensions", "rating_record", "anchor_record", "metrics"]
)
def test_calibration_certificate_rejects_malformed_nested_objects(fault):
    judge = reviewer(lambda *args: None)
    cert = certificate(judge.route_hashes)
    first = cert["anchors"][0]
    if fault == "expected":
        first["expected"] = DATA["dimension_names"]
    elif fault == "rating_dimensions":
        first["ratings"][0]["dimensions"] = DATA["dimension_names"]
    elif fault == "rating_record":
        first["ratings"][0] = None
    elif fault == "anchor_record":
        cert["anchors"][0] = None
    else:
        first["metrics"] = []
    with pytest.raises(DomainError, match="RSI_INVALID_CONTRACT"):
        artifact_review.validate_calibration(cert, judge.route_hashes)


@pytest.mark.parametrize("value", DATA["nonobjects"])
async def test_calibration_rejects_bad_anchor_before_start_or_model_call(tmp_path, value):
    calls = []

    def factory(*args):
        calls.append(True)
        raise AssertionError("Malformed anchor must not start a model")

    root = tmp_path / "calibration"
    with pytest.raises(DomainError, match="RSI_INVALID_CONTRACT"):
        await artifact_review.calibrate_artifacts(
            fixture_settings(), profile(), [value] * 12, root, provider_factory=factory
        )
    assert not calls and not root.exists()
