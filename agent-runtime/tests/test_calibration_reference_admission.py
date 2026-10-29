"""All declared human references must be valid before any scoring provider is created."""

import base64
import json

import pytest
from test_improvement_artifact_daily_policy import configured_settings
from test_improvement_artifact_review import pack, profile, rating

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest
from roami_agent.improvement.evaluation.artifact_review import calibrate_artifacts
from roami_agent.improvement.evaluation.execution.executors import ProtocolFixtureModel
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


def references(tmp_path):
    anchors = []
    for family in ("presentation", "plan", "web"):
        for score in (1, 1, 3, 3):
            evidence = tmp_path / f"reference-{len(anchors)}.json"
            evidence.write_text(json.dumps(pack()))
            evidence.chmod(0o600)
            anchors.append(
                {
                    "id": family + str(len(anchors)),
                    "family": family,
                    "human_reference": True,
                    "human_rater": "Controlled fixture approval, not a real human label",
                    "expected": dict.fromkeys(DIMENSIONS, score),
                    "evidence_file": str(evidence),
                    "evidence_hash": pack()["content_hash"],
                }
            )
    return anchors


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize(
    "fault",
    [
        "unconfirmed_last",
        "missing_rater_last",
        "wrong_reference_hash",
        "missing_reference_hash",
        "missing_file_last",
        "changed_pack_last",
        "wrong_renderer_last",
        "changed_image_last",
        "missing_negative_family",
        "started_last",
    ],
)
async def test_invalid_late_reference_does_not_spend_on_earlier_references(tmp_path, shared, fault):
    anchors = references(tmp_path)
    root = tmp_path / "calibration"
    last = anchors[-1]
    evidence = tmp_path / "reference-11.json"
    if fault == "unconfirmed_last":
        last["human_reference"] = False
    elif fault == "missing_rater_last":
        last["human_rater"] = ""
    elif fault == "wrong_reference_hash":
        last["evidence_hash"] = "0" * 64
    elif fault == "missing_reference_hash":
        last.pop("evidence_hash")
    elif fault == "missing_file_last":
        evidence.unlink()
    elif fault == "changed_pack_last":
        changed = pack()
        changed["instruction"] = "Different artifact request, not approved."
        evidence.write_text(json.dumps(changed))
    elif fault in {"wrong_renderer_last", "changed_image_last"}:
        changed = pack()
        if fault == "wrong_renderer_last":
            changed["renderer_image"] = "sha256:" + "a" * 64
        else:
            changed["images"][0]["data"] = base64.b64encode(b"changed image").decode()
        changed["content_hash"] = digest(
            {key: value for key, value in changed.items() if key != "content_hash"}
        )
        last["evidence_hash"] = changed["content_hash"]
        evidence.write_text(json.dumps(changed))
    elif fault == "missing_negative_family":
        for anchor in anchors[-4:]:
            anchor["expected"] = dict.fromkeys(DIMENSIONS, 3)
    elif fault == "started_last":
        location = root / digest(last["id"])[:24]
        location.mkdir(mode=0o700, parents=True)
        root.chmod(0o700)
        (location / "started.json").write_text('{"prior":"preserve this receipt"}')
    calls = []

    def factory(settings, role):
        score = anchors[len(calls) // 2]["expected"]["correctness"]
        calls.append(role)
        return ProtocolFixtureModel([{"text": json.dumps(rating(score))}])

    try:
        with pytest.raises((DomainError, OSError, ValueError)):
            await calibrate_artifacts(
                configured_settings() if shared else Settings(),
                profile(),
                anchors,
                root,
                token_limit=1_000_000,
                provider_factory=factory,
                shared_daily_limit=shared,
            )
    finally:
        assert calls == [], f"Invalid reference admitted {len(calls)} scoring providers"
        assert not (root / "calibration-result.json").exists()
    if fault == "started_last":
        assert (location / "started.json").read_text() == '{"prior":"preserve this receipt"}'


async def test_started_calibration_uses_frozen_approved_inputs(tmp_path):
    anchors = references(tmp_path)
    original_hash = anchors[-1]["evidence_hash"]
    calls = []

    def factory(settings, role):
        if not calls:
            anchors[-1]["expected"]["correctness"] = 0
            (tmp_path / "reference-11.json").write_text("not the started input version")
        score = (1, 1, 3, 3)[(len(calls) // 2) % 4]
        calls.append(role)
        return ProtocolFixtureModel([{"text": json.dumps(rating(score))}])

    result = await calibrate_artifacts(
        configured_settings(),
        profile(),
        anchors,
        tmp_path / "calibration",
        provider_factory=factory,
        shared_daily_limit=True,
    )
    saved = json.loads((tmp_path / "calibration/calibration-result.json").read_text())
    assert result["passed"] and len(calls) == 24
    assert saved["anchors"][-1]["expected"] == dict.fromkeys(DIMENSIONS, 3)
    assert saved["anchors"][-1]["evidence_hash"] == original_hash
