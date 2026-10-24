"""Blind artifact ratings retain independent checks, evidence and budget provenance."""

import asyncio
import base64
import copy
import hashlib
import json

import pytest

from roami_agent.improvement.artifact_review import (
    PROTOCOL_HASH,
    ArtifactReviewer,
    calibrate_artifacts,
    episode_metrics,
    validate_calibration,
)
from roami_agent.improvement.contracts import DIMENSIONS, digest
from roami_agent.improvement.executors import ProtocolFixtureModel
from roami_agent.improvement.measurements import EpisodeBudget
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


def pack():
    data = b"fixture-rendered-image"
    value = {
        "schema_version": 1,
        "renderer_image": "sha256:" + "f" * 64,
        "instruction": "Assess this example artifact",
        "artifacts": [{"file": "plan.md", "sha256": "a" * 64}],
        "grounding": {"hard_checks": {"required": True}},
        "texts": [{"label": "plan.md", "text": "A concrete plan", "truncated": False}],
        "images": [
            {
                "label": "rendered page",
                "mime": "image/jpeg",
                "data": base64.b64encode(data).decode(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ],
    }
    return {**value, "content_hash": digest(value)}


def profile():
    return {
        "schema_version": 1,
        "renderer_image": "sha256:" + "f" * 64,
        "max_tokens": 32000,
        "seconds": 30,
        "reviewers": [
            {
                "id": name,
                "route": {
                    "endpoint": "https://model.invalid/v1",
                    "name": name,
                    "key_env": "RSI_FIXTURE_KEY",
                    "timeout_seconds": 30,
                    "capabilities": {"images": True},
                },
            }
            for name in ("artifact_a", "artifact_b")
        ],
    }


def rating(score=3):
    return {
        "dimensions": dict.fromkeys(DIMENSIONS, score),
        "evidence": [
            {
                "dimension": key,
                "label": "rendered page",
                "reason": "Specific visible observation for " + key,
            }
            for key in DIMENSIONS
        ],
    }


def certificate(routes):
    anchors = []
    for family in ("presentation", "plan", "web"):
        for score in (1, 1, 3, 3):
            anchors.append(
                {
                    "id": family + str(len(anchors)),
                    "family": family,
                    "human_reference": True,
                    "human_rater": "Fixture human label",
                    "evidence_hash": "a" * 64,
                    "expected": dict.fromkeys(DIMENSIONS, score),
                    "ratings": [
                        {"rater": r, "blind": True, "dimensions": dict.fromkeys(DIMENSIONS, score)}
                        for r in routes
                    ],
                    "metrics": {"token_coverage": "complete", "tokens": 100, "model_calls": 2},
                }
            )
    return {
        "schema_version": 1,
        "renderer_image": "sha256:" + "f" * 64,
        "protocol_hash": PROTOCOL_HASH,
        "route_hashes": routes,
        "anchors": anchors,
        "provider_mode": "protocol_fixture",
    }


def reviewer(factory):
    raw = profile()
    draft = ArtifactReviewer(Settings(), raw, provider_factory=factory, calibrated=False)
    return ArtifactReviewer(
        Settings(),
        {**raw, "certificate": certificate(draft.route_hashes)},
        provider_factory=factory,
    )


@pytest.mark.parametrize(
    "fault",
    [
        "protocol",
        "routes",
        "missing_family",
        "no_negative",
        "not_human",
        "disagreement",
        "unknown_usage",
    ],
)
def test_calibration_requires_same_models_balanced_human_labels_and_known_usage(fault):
    draft = ArtifactReviewer(Settings(), profile(), calibrated=False)
    cert = certificate(draft.route_hashes)
    if fault == "protocol":
        cert["protocol_hash"] = "changed"
    if fault == "routes":
        cert["route_hashes"] = {}
    if fault == "missing_family":
        cert["anchors"] = [a for a in cert["anchors"] if a["family"] != "web"]
    if fault == "no_negative":
        for a in cert["anchors"]:
            a["expected"] = dict.fromkeys(DIMENSIONS, 3)
            for r in a["ratings"]:
                r["dimensions"] = dict.fromkeys(DIMENSIONS, 3)
    if fault == "not_human":
        cert["anchors"][0]["human_reference"] = False
    if fault == "disagreement":
        cert["anchors"][0]["ratings"][1]["dimensions"]["usability"] = 3
    if fault == "unknown_usage":
        cert["anchors"][0]["metrics"]["token_coverage"] = "unknown"
    with pytest.raises(DomainError):
        validate_calibration(cert, draft.route_hashes)


def test_model_aliases_and_fixture_calibration_are_not_production_ready():
    raw = profile()
    raw["reviewers"][1]["route"]["name"] = "artifact_a"
    with pytest.raises(DomainError, match="INDEPENDENT"):
        ArtifactReviewer(Settings(), raw, calibrated=False)
    raw = profile()
    draft = ArtifactReviewer(Settings(), raw, calibrated=False)
    raw["certificate"] = certificate(draft.route_hashes)
    with pytest.raises(DomainError, match="NOT_PRODUCTION"):
        ArtifactReviewer(Settings(), raw)


async def test_raters_receive_identical_blind_evidence_and_authoritative_usage():
    calls = []

    class Model(ProtocolFixtureModel):
        async def stream(self, messages, tools):
            calls.append((copy.deepcopy(messages), copy.deepcopy(tools)))
            async for event in super().stream(messages, tools):
                yield event

    judge = reviewer(lambda s, r: Model([{"text": json.dumps(rating())}]))
    budget = judge.budget()
    journal = []
    ratings = await judge.rate(pack(), budget, journal)
    assert len(ratings) == 2 and calls[0] == calls[1] and calls[0][1] == []
    assert budget.metrics()["tokens"] == 240 and {r["role"] for r in journal} == {
        "artifact_a",
        "artifact_b",
    }
    assert not any(
        word in calls[0][0][1]["content"][0]["text"] for word in ("baseline", "candidate", "arm")
    )


@pytest.mark.parametrize(
    "fault", ["bad_hash", "bad_json", "fake_evidence", "missing_dimension", "unknown_usage"]
)
async def test_no_paid_output_replay_or_fabricated_evidence(fault):
    calls = []
    output = rating()
    if fault == "fake_evidence":
        output["evidence"][0]["label"] = "not supplied"
    if fault == "missing_dimension":
        output["evidence"][0]["dimension"] = "usability"

    class Model(ProtocolFixtureModel):
        async def stream(self, messages, tools):
            calls.append(messages)
            if fault == "unknown_usage":
                yield ModelEvent("text", json.dumps(output))
                return
            async for event in super().stream(messages, tools):
                yield event

    judge = reviewer(
        lambda s, r: Model([{"text": "not json" if fault == "bad_json" else json.dumps(output)}])
    )
    evidence = pack()
    if fault == "bad_hash":
        evidence["images"][0]["data"] = base64.b64encode(b"replaced").decode()
    with pytest.raises((DomainError, ValueError)):
        await judge.rate(evidence, judge.budget(), [])
    assert len(calls) == (0 if fault == "bad_hash" else 1)


@pytest.mark.parametrize("disagree", [False, True])
async def test_hard_evidence_retained_and_rating_disagreement_stays_pending(
    monkeypatch, tmp_path, disagree
):
    from roami_agent.improvement import artifact_review

    async def evidence(*args):
        return pack()

    monkeypatch.setattr(artifact_review, "collect_artifact_evidence", evidence)
    judge = reviewer(
        lambda s, r: ProtocolFixtureModel(
            [{"text": json.dumps(rating(2 if disagree and r == "artifact_b" else 3))}]
        )
    )
    original = {
        "hard_passed": True,
        "pending": True,
        "passed": False,
        "quality": 0,
        "checks": {"native": True},
        "native_partial": {"unscored_points": 7},
    }
    result = await judge.review(
        {"grading_profile": "presentation"},
        original,
        tmp_path,
        None,
        budget=judge.budget(),
        journal=[],
    )
    assert result["passed"] is (not disagree) and result["pending"] is disagree
    assert (
        result["hard_checks"] == original["checks"]
        and result["native_partial"] == original["native_partial"]
    )
    assert (
        json.loads((tmp_path / "artifact-review.json").read_text())["metrics"]["model_calls"] == 2
    )


async def test_cancellation_persists_unknown_usage(monkeypatch, tmp_path):
    from roami_agent.improvement import artifact_review

    async def evidence(*args):
        return pack()

    monkeypatch.setattr(artifact_review, "collect_artifact_evidence", evidence)

    class Model:
        model = "fixture"

        async def stream(self, *args):
            raise asyncio.CancelledError
            yield

    judge = reviewer(lambda s, r: Model())
    budget = judge.budget()
    with pytest.raises(asyncio.CancelledError):
        await judge.review(
            {"grading_profile": "presentation"},
            {"hard_passed": True, "pending": True, "checks": {}},
            tmp_path,
            None,
            budget=budget,
            journal=[],
        )
    record = json.loads((tmp_path / "artifact-review.json").read_text())
    assert record["metrics"]["token_coverage"] == "unknown" and budget.unknown
    primary = EpisodeBudget({"tokens": 10000, "seconds": 10, "requests": 1})
    assert episode_metrics(primary, budget)["tokens"] is None


async def test_calibration_started_marker_prevents_replay(tmp_path):
    evidence = tmp_path / "pack.json"
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
                    "human_rater": "Fixture label",
                    "expected": dict.fromkeys(DIMENSIONS, score),
                    "evidence_file": str(evidence),
                }
            )
    counter = 0

    def factory(settings, role):
        nonlocal counter
        score = (1, 1, 3, 3)[(counter // 2) % 4]
        counter += 1
        return ProtocolFixtureModel([{"text": json.dumps(rating(score))}])

    root = tmp_path / "calibration"
    result = await calibrate_artifacts(
        Settings(), profile(), anchors, root, token_limit=100000, provider_factory=factory
    )
    assert result["passed"] and result["provider_mode"] == "protocol_fixture" and counter == 24
    with pytest.raises(FileExistsError):
        await calibrate_artifacts(
            Settings(), profile(), anchors, root, token_limit=100000, provider_factory=factory
        )
    assert counter == 24


async def test_old_mechanism_selection_is_rejected_before_container_execution(tmp_path):
    from pathlib import Path
    from types import SimpleNamespace

    from roami_agent.improvement.mechanisms import nodes, run_mechanism

    case = {"id": "MECH-PL01", "judge": {"kind": "mechanism", "selectors": nodes("MECH-PL01")[:-1]}}
    executor = SimpleNamespace(regression_root=Path(__file__).parent)
    with pytest.raises(DomainError, match="REGRESSION_PACK_CHANGED"):
        await run_mechanism(case, {}, tmp_path, executor)


async def test_rater_output_budget_is_explicit_and_labels_are_advertised():
    raw = profile()
    raw["output_tokens"] = 4096
    observed = []

    def factory(settings, role):
        observed.append(settings.route("main").parameters["max_tokens"])
        return ProtocolFixtureModel([{"text": json.dumps(rating())}])

    judge = ArtifactReviewer(Settings(), raw, provider_factory=factory, calibrated=False)
    journal = []
    await judge.rate(pack(), judge.budget(), journal)
    assert observed == [4096, 4096]
    sent = json.loads(journal[0]["messages"][-1]["content"][0]["text"])
    assert set(sent["allowed_labels"]) == {"plan.md", "rendered page"}
    changed = ArtifactReviewer(Settings(), profile(), calibrated=False)
    assert changed.route_hashes != judge.route_hashes


async def test_renderer_cannot_replace_the_agent_under_test(monkeypatch):
    from types import SimpleNamespace

    from roami_agent.improvement import containers

    agent_image = "sha256:" + "a" * 64
    renderer_image = "sha256:" + "b" * 64

    async def docker(*args, **kwargs):
        assert args[:2] == ("image", "inspect")
        return json.dumps(
            [{"Id": agent_image if args[2] == containers.IMAGE else renderer_image}]
        ).encode()

    monkeypatch.setattr(containers, "docker_command", docker)
    reviewer = SimpleNamespace(profile={"renderer_image": renderer_image}, content_hash="reviewer")
    executor = containers.ContainerExecutor(Settings(), artifact_reviewer=reviewer)
    result = await executor.preflight()
    assert executor.image == containers.IMAGE and executor.image_id == agent_image
    assert executor.artifact_renderer.image_id == renderer_image
    assert result["artifact_renderer_image_id"] == renderer_image
