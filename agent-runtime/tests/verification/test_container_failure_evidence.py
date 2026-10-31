"""An actual read-only sandbox failure retains its host stderr receipt."""

import os

import pytest

from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.integrations.container_failure_evidence import capture_failures
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


async def test_actual_readonly_sandbox_retains_failure_and_removes_container(tmp_path):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image:
        pytest.skip("pinned local RSI image required")
    executor = ContainerExecutor(Settings(), image=image)

    @capture_failures
    async def run():
        try:
            await executor.sandbox(
                tmp_path,
                "from pathlib import Path;Path('/workspace/denied.json').write_text('synthetic')",
                timeout=30,
            )
        except DomainError as error:
            return {"grade": {"passed": False, "reason": error.code}}
        pytest.fail("Read-only sandbox unexpectedly allowed a host write")

    result = await run()
    assert not result["grade"]["passed"]
    assert result["grade"]["reason"] == "RSI_DOCKER_COMMAND_FAILED"
    rows = result["execution_diagnostics"]["failures"]
    assert len(rows) == 1
    assert rows[0]["operation"] == "start" and rows[0]["exit_code"] == 1
    assert "Read-only file system" in rows[0]["stderr"] and "denied.json" in rows[0]["stderr"]
    assert not (tmp_path / "denied.json").exists()
