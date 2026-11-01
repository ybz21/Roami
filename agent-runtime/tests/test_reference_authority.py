"""Delegated AI references remain explicit through calibration and certificate loading."""

import copy
import json
from pathlib import Path

import pytest
from test_improvement_artifact_review import certificate, fixture_settings, pack, profile, rating

from roami_agent.improvement.domain.contracts import DIMENSIONS
from roami_agent.improvement.domain.reference_authority import (
    AUTHORIZED_AI,
    HUMAN_ONLY,
    reference_kind,
)
from roami_agent.improvement.evaluation.artifact_review import (
    ArtifactReviewer,
    calibrate_artifacts,
    validate_calibration,
)
from roami_agent.improvement.evaluation.artifact_review_receipts import review_summary
from roami_agent.improvement.evaluation.execution.executors import ProtocolFixtureModel
from roami_agent.protocol.errors import DomainError

DATA = json.loads(
    Path(__file__).with_name("fixtures").joinpath("reference-authority.json").read_text()
)


def delegated(anchor):
    anchor = copy.deepcopy(anchor)
    anchor.update(human_reference=False, human_rater="")
    anchor["reference_provenance"] = {
        "kind": "user_authorized_ai",
        "reviewer": DATA["ai_reviewer"],
        "authorization": DATA["authorization"],
        "evidence_hash": anchor["evidence_hash"],
        "expected": copy.deepcopy(anchor["expected"]),
    }
    return anchor


def anchor():
    return {
        "human_reference": True,
        "human_rater": DATA["human_rater"],
        "evidence_hash": "a" * 64,
        "expected": dict.fromkeys(DIMENSIONS, 3),
    }


def test_delegated_reference_requires_explicit_policy_and_preserves_source():
    source = delegated(anchor())
    before = copy.deepcopy(source)
    assert reference_kind(source, AUTHORIZED_AI) == "user_authorized_ai"
    assert source == before and source["human_reference"] is False
    with pytest.raises(DomainError, match="REFERENCE_POLICY"):
        reference_kind(source, HUMAN_ONLY)
    assert reference_kind(anchor(), HUMAN_ONLY) == "human"
    assert reference_kind(anchor(), AUTHORIZED_AI) == "human"


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "list",
        "human_flag",
        "human_rater",
        "kind",
        "reviewer",
        "authorization",
        "hash",
        "score",
        "bool_score",
        "extra",
        "long_reviewer",
        "long_authorization",
    ],
)
def test_unbound_or_mislabeled_ai_decisions_are_rejected(fault):
    source = delegated(anchor())
    provenance = source["reference_provenance"]
    if fault == "missing":
        source.pop("reference_provenance")
    elif fault == "list":
        source["reference_provenance"] = list(provenance)
    elif fault == "human_flag":
        source["human_reference"] = True
    elif fault == "human_rater":
        source["human_rater"] = "Misrepresented as human"
    elif fault == "kind":
        provenance["kind"] = "human"
    elif fault in ("reviewer", "authorization"):
        provenance[fault] = " "
    elif fault == "hash":
        source["evidence_hash"] = "b" * 64
    elif fault == "score":
        source["expected"]["usability"] = 2
    elif fault == "bool_score":
        provenance["expected"]["usability"] = True
        source["expected"]["usability"] = 1
    elif fault == "long_reviewer":
        provenance["reviewer"] = " " * 100 + "x"
    elif fault == "long_authorization":
        provenance["authorization"] = " " * 2000 + "x"
    else:
        provenance["unexpected"] = True
    with pytest.raises(DomainError, match="REFERENCE_PROVENANCE"):
        reference_kind(source, AUTHORIZED_AI)


def test_mixed_certificate_requires_matching_reference_policy():
    judge = ArtifactReviewer(fixture_settings(), profile(), calibrated=False)
    cert = certificate(judge.route_hashes)
    cert["reference_policy"] = AUTHORIZED_AI
    cert["anchors"][2] = delegated(cert["anchors"][2])
    validate_calibration(cert, judge.route_hashes, reference_policy=AUTHORIZED_AI)
    with pytest.raises(DomainError, match="CALIBRATION_CHANGED"):
        validate_calibration(cert, judge.route_hashes)
    cert["anchors"][2]["human_reference"] = True
    with pytest.raises(DomainError, match="REFERENCE_PROVENANCE"):
        validate_calibration(cert, judge.route_hashes, reference_policy=AUTHORIZED_AI)


def mixed_inputs(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(pack()))
    evidence.chmod(0o600)
    anchors = []
    for family in ("presentation", "plan", "web"):
        for score in (1, 1, 3, 3):
            anchors.append(
                {
                    "id": family + str(len(anchors)),
                    "family": family,
                    "human_reference": True,
                    "human_rater": DATA["human_rater"],
                    "expected": dict.fromkeys(DIMENSIONS, score),
                    "evidence_file": str(evidence),
                    "evidence_hash": pack()["content_hash"],
                }
            )
    for index in DATA["delegated_indices"]:
        anchors[index] = delegated(anchors[index])
    return anchors


async def test_mixed_calibration_round_trip_keeps_eight_human_and_four_ai(tmp_path):
    anchors = mixed_inputs(tmp_path)
    before = copy.deepcopy(anchors)
    calls = 0

    def factory(settings, role):
        nonlocal calls
        score = (1, 1, 3, 3)[(calls // 2) % 4]
        calls += 1
        return ProtocolFixtureModel([{"text": json.dumps(rating(score))}])

    raw = {**profile(), "reference_policy": AUTHORIZED_AI}
    result = await calibrate_artifacts(
        fixture_settings(), raw, anchors, tmp_path / "calibration", provider_factory=factory
    )
    assert calls == 24 and anchors == before
    assert result["reference_basis_counts"] == {"human": 8, "user_authorized_ai": 4}
    cert = json.loads((tmp_path / "calibration/calibration-result.json").read_text())
    assert cert["reference_policy"] == AUTHORIZED_AI
    for index in DATA["delegated_indices"]:
        assert cert["anchors"][index]["human_reference"] is False
        assert cert["anchors"][index]["human_rater"] == ""
        assert (
            cert["anchors"][index]["reference_provenance"] == anchors[index]["reference_provenance"]
        )
    loaded = ArtifactReviewer(
        fixture_settings(), {**raw, "certificate": cert}, provider_factory=factory
    )
    assert loaded.reference_policy == AUTHORIZED_AI
    assert calls == 24
    with pytest.raises(FileExistsError):
        await calibrate_artifacts(
            fixture_settings(), raw, anchors, tmp_path / "calibration", provider_factory=factory
        )
    assert calls == 24


@pytest.mark.parametrize(
    "fault", ["default_policy", "changed_evidence", "changed_score", "missing_authorization"]
)
async def test_unapproved_or_changed_reference_blocks_before_model_calls(tmp_path, fault):
    anchors = mixed_inputs(tmp_path)
    raw = {**profile(), "reference_policy": AUTHORIZED_AI}
    last = anchors[DATA["delegated_indices"][-1]]
    if fault == "default_policy":
        raw.pop("reference_policy")
    elif fault == "changed_evidence":
        last["evidence_hash"] = "b" * 64
    elif fault == "changed_score":
        last["expected"]["usability"] = 2
    else:
        last["reference_provenance"].pop("authorization")
    calls = []

    def forbidden(*args):
        calls.append(args)
        raise AssertionError("Invalid reference reached a model provider")

    root = tmp_path / "calibration"
    with pytest.raises(DomainError, match="REFERENCE_"):
        await calibrate_artifacts(
            fixture_settings(), raw, anchors, root, provider_factory=forbidden
        )
    assert not calls and not list(root.rglob("started.json"))


def review_receipt():
    return {
        "schema_version": 1,
        "ratings": [],
        "error": "RSI_ARTIFACT_REVIEW_FAILED",
        "reference_policy": AUTHORIZED_AI,
        "reference_basis_counts": {"human": 8, "user_authorized_ai": 4},
    }


def test_review_summary_keeps_reference_source_counts_without_sharing_mutable_values():
    receipt = review_receipt()
    summary = review_summary(receipt)
    assert summary["reference_policy"] == AUTHORIZED_AI
    assert summary["reference_basis_counts"] == {"human": 8, "user_authorized_ai": 4}
    summary["reference_basis_counts"]["human"] = 0
    assert receipt["reference_basis_counts"]["human"] == 8


@pytest.mark.parametrize("fault", ["bool_count", "wrong_policy", "unknown_policy"])
def test_review_summary_rejects_misrepresented_reference_sources(fault):
    receipt = review_receipt()
    if fault == "bool_count":
        receipt["reference_basis_counts"]["human"] = True
    elif fault == "wrong_policy":
        receipt["reference_policy"] = HUMAN_ONLY
    else:
        receipt["reference_policy"] = "unknown"
    assert review_summary(receipt) is None
