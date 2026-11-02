"""Stopped slide checks retain the original verifier window without resuming generation."""

import asyncio
import base64
import hashlib
import json
import time

import pytest
from test_improvement import case
from test_improvement_slide_receipts import fixture
from test_improvement_timeout_assessment import media_case, stopped_executor

from roami_agent.improvement.evaluation.execution import containers
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


class VerifierClock:
    def __init__(self, monkeypatch):
        loop = asyncio.get_running_loop()
        original = loop.time
        self.offset = 0
        monkeypatch.setattr(loop, "time", lambda: original() + self.offset)

    async def advance(self, seconds):
        self.offset += seconds
        for _ in range(3):
            await asyncio.sleep(0)


def slide_case(tmp_path):
    spec = fixture(tmp_path)
    return case(
        "slide-window",
        files={},
        asset_files={
            name: base64.b64encode((tmp_path / name).read_bytes()).decode()
            for name in ("input.pptx", "updated.pptx")
        },
        limits={"seconds": 1, "tokens": 1, "requests": 1},
        judge={"kind": "slides", **spec["judge"]},
        origin=spec["origin"],
    )


@pytest.mark.parametrize("preparation,comparison,cleanup", [(0, 95, 0), (25, 175, 25)])
@pytest.mark.parametrize("score", [0, 1])
async def test_stopped_slide_verifier_can_finish_within_its_original_window(
    tmp_path, monkeypatch, preparation, comparison, cleanup, score
):
    item = slide_case(tmp_path)
    executor, events = stopped_executor(tmp_path, monkeypatch)
    clock = VerifierClock(monkeypatch)
    snapshots = {}

    async def sandbox(workspace, program, **options):
        assert events == ["stopped", "recovered"]
        assert options["timeout"] == 180
        snapshots.update(
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in workspace.iterdir()
                if p.is_file()
            }
        )
        async with asyncio.timeout(30):
            await clock.advance(preparation)
        async with asyncio.timeout(30):
            await clock.advance(preparation)
        async with asyncio.timeout(options["timeout"]):
            await clock.advance(comparison)
        for _ in range(2):
            async with asyncio.timeout(30):
                await clock.advance(cleanup)
        events.append("assessed")
        return json.dumps({"results": [score, score], "errors": []}).encode()

    monkeypatch.setattr(executor, "sandbox", sandbox)
    try:
        result = await executor.run(item, {}, tmp_path)
        assert events == ["stopped", "recovered", "assessed"]
        assert result["grade"]["reason"] == "RSI_TIME_BUDGET"
        assert not result["grade"]["passed"] and not result["verified_delivery"]
        assert result["grade"]["native_metric"] == score
        assert result["grade"]["native_reference_results"] == [score, score]
        assert result["metrics"]["tokens"] == result["metrics"]["model_calls"] == 0
        assert result["metrics"]["elapsed_ms"] is None
        assert item["limits"]["seconds"] == 1
        summary = trial_summary(item, result)
        assert summary["native_judgment"]["native_metric"] == score
        assert summary["native_judgment"]["artifact_assessment_after_timeout"] is True
        assert all(
            hashlib.sha256((tmp_path / "workspace" / name).read_bytes()).hexdigest() == sha
            for name, sha in snapshots.items()
        )
    finally:
        clock.offset = 0


@pytest.mark.parametrize("preparation,comparison", [(31, 0), (25, 181)])
@pytest.mark.parametrize("kind", ["slides", "media"])
async def test_preparation_and_original_verifier_timeouts_remain_unscored(
    tmp_path, monkeypatch, preparation, comparison, kind
):
    item = slide_case(tmp_path) if kind == "slides" else media_case()
    if kind == "media":
        item["asset_files"]["output/enhanced.wav"] = item["asset_files"]["materials/noisy.wav"]
        comparison = 331 if comparison else 0
    executor, events = stopped_executor(tmp_path, monkeypatch)
    clock = VerifierClock(monkeypatch)

    async def sandbox(*args, **options):
        async with asyncio.timeout(30):
            await clock.advance(preparation)
        async with asyncio.timeout(options["timeout"]):
            await clock.advance(comparison)
        pytest.fail("An overlong verifier must not publish a score")

    monkeypatch.setattr(executor, "sandbox", sandbox)
    try:
        result = await executor.run(item, {}, tmp_path)
        assert events == ["stopped", "recovered"]
        assert result["grade"]["reason"] == "RSI_TIME_BUDGET"
        assert not result["grade"]["passed"] and "native_metric" not in result["grade"]
        assert result["grade"]["native_verifier_ran"] is False
        assert result["metrics"]["tokens"] == result["metrics"]["model_calls"] == 0
    finally:
        clock.offset = 0


async def test_post_timeout_slide_window_still_cancels_a_stalled_grader(tmp_path, monkeypatch):
    item = slide_case(tmp_path)
    executor, _ = stopped_executor(tmp_path, monkeypatch)
    clock = VerifierClock(monkeypatch)
    cancelled = []

    async def sandbox(*args, **kwargs):
        try:
            await clock.advance(301)
            pytest.fail("Outer assessment window must remain bounded")
        finally:
            cancelled.append(True)

    monkeypatch.setattr(executor, "sandbox", sandbox)
    try:
        result = await executor.run(item, {}, tmp_path)
        assert result["grade"]["artifact_assessment_error"] == "RSI_ARTIFACT_ASSESSMENT_TIMEOUT"
        assert (
            result["grade"]["reason"] == "RSI_TIME_BUDGET"
            and "native_metric" not in result["grade"]
        )
        assert cancelled == [True]
    finally:
        clock.offset = 0


async def test_larger_assessment_window_does_not_extend_generation_deadline(tmp_path, monkeypatch):
    item = slide_case(tmp_path)
    executor = containers.ContainerExecutor(Settings())

    async def forbidden(*args, **kwargs):
        pytest.fail("Expired generation must stop before normal verification")

    monkeypatch.setattr(executor, "sandbox", forbidden)
    with pytest.raises(DomainError, match="RSI_TIME_BUDGET"):
        await executor.verify(item, tmp_path, "", started=time.monotonic() - 2)


@pytest.mark.parametrize("score", [0, 1])
async def test_media_control_operations_do_not_consume_its_original_verifier_window(
    tmp_path, monkeypatch, score
):
    item = media_case()
    item["asset_files"]["output/enhanced.wav"] = item["asset_files"]["materials/noisy.wav"]
    executor, events = stopped_executor(tmp_path, monkeypatch)
    clock = VerifierClock(monkeypatch)

    async def sandbox(*args, **options):
        assert events == ["stopped", "recovered"] and options["timeout"] == 330
        for _ in range(2):
            async with asyncio.timeout(30):
                await clock.advance(25)
        async with asyncio.timeout(options["timeout"]):
            await clock.advance(325)
        for _ in range(2):
            async with asyncio.timeout(30):
                await clock.advance(25)
        return json.dumps(
            {"reward": score, "checks": {"verifier_exited": True, "verifier_result_valid": True}}
        ).encode()

    monkeypatch.setattr(executor, "sandbox", sandbox)
    try:
        result = await executor.run(item, {}, tmp_path)
        assert result["grade"]["native_metric"] == score
        assert result["grade"]["reason"] == "RSI_TIME_BUDGET"
        assert result["grade"]["artifact_assessment_after_timeout"] is True
        assert not result["grade"]["passed"] and not result["verified_delivery"]
        assert result["metrics"]["tokens"] == result["metrics"]["model_calls"] == 0
        assert item["limits"]["seconds"] == 1
    finally:
        clock.offset = 0
