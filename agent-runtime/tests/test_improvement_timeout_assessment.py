"""Stopped executions keep real model-free artifact scores without becoming passes."""

import asyncio
import base64
import json
import time

import pytest
from test_improvement import case
from test_improvement_media import wav

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.execution import containers
from roami_agent.improvement.evaluation.native_judgment import native_judgment, report_judgments
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.artifact_files import materialize
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


def stopped_executor(tmp_path, monkeypatch, *, failure=None, cleanup_failure=False):
    events = []

    async def docker(*args, **kwargs):
        if args[0] == "start":
            raise failure or TimeoutError()
        return b""

    async def remove(*args):
        events.append("stopped")
        if cleanup_failure:
            raise DomainError("RSI_DOCKER_CLEANUP_FAILED")

    async def recover(*args):
        events.append("recovered")

    def forbidden(*args):
        pytest.fail("Artifact assessment must not create a model provider")

    monkeypatch.setattr(containers, "docker_command", docker)
    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.benchmarks.slide_tasks.prepare_slides",
        lambda *args: None,
    )
    executor = containers.ContainerExecutor(Settings(), provider_factory=forbidden)
    executor.image_id = "fixture-image"
    monkeypatch.setattr(executor, "remove", remove)
    monkeypatch.setattr(executor, "recover_execution", recover)
    return executor, events


@pytest.mark.parametrize("kind", ["media", "slides"])
@pytest.mark.parametrize("score", [0, 1])
async def test_timeout_stops_execution_before_assessing_and_never_becomes_a_pass(
    tmp_path, monkeypatch, kind, score
):
    executor, events = stopped_executor(tmp_path, monkeypatch)

    async def verify(*args, **kwargs):
        assert events == ["stopped", "recovered"]
        assert kwargs["after_timeout"] is True
        events.append("assessed")
        return {
            "passed": True,
            "hard_passed": True,
            "quality": 100,
            "pending": False,
            "reason": "assertions_passed",
            "native_metric": score,
            "native_verifier_ran": True,
            "artifact_assessment_after_timeout": True,
        }

    monkeypatch.setattr(executor, "verify", verify)
    item = case("timeout", judge={"kind": kind})
    result = await executor.run(item, {}, tmp_path)
    assert events == ["stopped", "recovered", "assessed"]
    grade = result["grade"]
    assert grade["reason"] == "RSI_TIME_BUDGET" and grade["execution_error"] == "RSI_TIME_BUDGET"
    assert not grade["passed"] and not grade["hard_passed"] and not result["verified_delivery"]
    assert (
        grade["native_metric"] == score and grade["artifact_assessment"]["native_metric"] == score
    )
    assert result["metrics"]["tokens"] == result["metrics"]["model_calls"] == 0
    assert result["metrics"]["elapsed_ms"] is None and result["metrics"]["right_censored"]
    summary = trial_summary(item, result)
    assert summary["native_judgment"]["native_metric"] == score
    assert summary["native_judgment"]["artifact_assessment_after_timeout"] is True
    assert summary["metrics"]["artifact_assessment_ms"] >= 0
    assert report_judgments([summary])[0]["artifact_assessment_after_timeout"] is True


@pytest.mark.parametrize(
    "error,expected",
    [
        (TimeoutError(), "RSI_ARTIFACT_ASSESSMENT_TIMEOUT"),
        (DomainError("RSI_VERIFIER_CHANGED"), "RSI_VERIFIER_CHANGED"),
    ],
)
async def test_assessment_failure_keeps_primary_timeout_and_has_no_fake_score(
    tmp_path, monkeypatch, error, expected
):
    executor, _ = stopped_executor(tmp_path, monkeypatch)

    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(executor, "verify", fail)
    result = await executor.run(case("timeout", judge={"kind": "media"}), {}, tmp_path)
    assert result["grade"]["reason"] == "RSI_TIME_BUDGET"
    evidence = native_judgment(result["grade"])
    assert evidence["artifact_assessment_error"] == expected
    assert evidence["artifact_assessment_after_timeout"] is True
    assert evidence["native_verifier_ran"] is False and "native_metric" not in evidence


@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_auth_failure_or_unstopped_execution_does_not_start_assessment(
    tmp_path, monkeypatch, cleanup_failure
):
    executor, _ = stopped_executor(
        tmp_path,
        monkeypatch,
        failure=None if cleanup_failure else DomainError("MODEL_HTTP_401"),
        cleanup_failure=cleanup_failure,
    )

    async def forbidden(*args, **kwargs):
        pytest.fail("No artifact grading before a verified stop or on authentication failure")

    monkeypatch.setattr(executor, "verify", forbidden)
    item = case("timeout", judge={"kind": "media"})
    if cleanup_failure:
        with pytest.raises(DomainError, match="RSI_DOCKER_CLEANUP_FAILED"):
            await executor.run(item, {}, tmp_path)
    else:
        assert (await executor.run(item, {}, tmp_path))["grade"]["reason"] == "MODEL_HTTP_401"


def media_case():
    return case(
        "audio",
        files={},
        asset_files={"materials/noisy.wav": base64.b64encode(wav(64)).decode()},
        limits={"seconds": 1, "tokens": 1, "requests": 1},
        judge={
            "kind": "media",
            "media_kind": "repair",
            "upstream_verifier": "fixture",
            "minimum_reward": 0.8,
            "golden": {},
        },
        origin={"verifier_sha256": digest("fixture")},
    )


async def test_post_timeout_original_verifier_is_bounded_and_does_not_reset_execution_budget(
    tmp_path, monkeypatch
):
    item = media_case()
    workspace = tmp_path / "workspace"
    materialize(item, workspace)
    (workspace / "output").mkdir(exist_ok=True)
    (workspace / "output/enhanced.wav").write_bytes(wav(64))
    executor = containers.ContainerExecutor(Settings())
    cancelled = []

    async def sandbox(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(executor, "sandbox", sandbox)
    monkeypatch.setitem(containers.POST_TIMEOUT_ASSESSMENT_SECONDS, "media", 0.01)
    expired = time.monotonic() - 10
    with pytest.raises(DomainError, match="RSI_TIME_BUDGET"):
        await executor.verify(item, workspace, "", started=expired)
    with pytest.raises(TimeoutError):
        await executor.verify(item, workspace, "", started=expired, after_timeout=True)
    assert cancelled == [True] and item["limits"]["seconds"] == 1


async def test_post_timeout_media_receipt_preserves_actual_score(tmp_path, monkeypatch):
    item = media_case()
    workspace = tmp_path / "workspace"
    materialize(item, workspace)
    (workspace / "output").mkdir(exist_ok=True)
    (workspace / "output/enhanced.wav").write_bytes(wav(64))
    executor = containers.ContainerExecutor(Settings())

    async def sandbox(*args, **kwargs):
        return json.dumps(
            {"reward": 0.1096, "checks": {"verifier_exited": True, "verifier_result_valid": True}}
        ).encode()

    monkeypatch.setattr(executor, "sandbox", sandbox)
    grade = await executor.verify(
        item, workspace, "", started=time.monotonic() - 10, after_timeout=True
    )
    evidence = native_judgment(grade)
    assert evidence["native_metric"] == 0.1096 and evidence["native_metric_minimum"] == 0.8
    assert (
        evidence["native_verifier_ran"] is True
        and evidence["artifact_assessment_after_timeout"] is True
    )
    assert not grade["passed"]


async def test_post_timeout_cannot_invoke_an_arbitrary_judge(tmp_path):
    executor = containers.ContainerExecutor(Settings())
    with pytest.raises(DomainError, match="RSI_ARTIFACT_ASSESSMENT_UNSUPPORTED"):
        await executor.verify(
            case(), tmp_path, "", started=time.monotonic() - 10, after_timeout=True
        )
