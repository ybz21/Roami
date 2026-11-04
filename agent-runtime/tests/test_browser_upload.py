"""Upload admission preserves workspace and browser operation identity."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from roami_agent.executors.browser_driver import BrowserDriver
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tool_arguments import ToolArgumentsError
from roami_agent.tools.browser import register_browser_tools
from roami_agent.tools.command_families import chrome_operation
from roami_agent.tools.model_inputs import register_model_inputs


def upload_driver():
    driver = object.__new__(BrowserDriver)
    driver.resources = SimpleNamespace(
        scope=AsyncMock(return_value={"owner": "alice", "taskId": "task", "runId": "run"}),
        observation=AsyncMock(
            return_value={
                "id": "observed",
                "resource_id": "resource",
                "scene_epoch": 4,
                "lease_epoch": 2,
                "body_json": json.dumps({"signature": "a" * 64}),
            }
        ),
        resource=AsyncMock(
            return_value={
                "id": "resource",
                "kind": "browser",
                "resource_key": "browser:browser-id:target:target-id",
            }
        ),
    )
    driver.artifacts = SimpleNamespace(max_bytes=4_000_000)
    driver._perform = AsyncMock(
        return_value={
            "operationId": "b" * 32,
            "driverState": "succeeded",
            "output": json.dumps(
                {
                    "selected": True,
                    "file": {"name": "demo clip.mp4", "sizeBytes": 15, "sha256": "c" * 64},
                }
            ),
        }
    )
    driver.observe = AsyncMock(return_value={"observation": {"id": "next"}})
    return driver


async def test_upload_passes_scoped_file_and_existing_operation_context(tmp_path):
    driver = upload_driver()
    path = str(tmp_path / "artifacts" / "demo clip.mp4")
    binding = {"workspace": {"directory": str(tmp_path)}, "taskId": "task", "runId": "run"}
    result = await driver.act(
        {
            "kind": "upload",
            "selector": "#video",
            "path": path,
            "sha256": "c" * 64,
            "observationId": "observed",
        },
        binding,
    )
    driver.resources.scope.assert_awaited_once_with(binding, input_action=True)
    call = driver._perform.await_args
    assert call.args[3] is binding
    assert call.args[4:] == (
        "upload",
        [
            "--target",
            "target-id",
            "#video",
            path,
            "--file-root",
            str(tmp_path),
            "--expected-file-sha256",
            "c" * 64,
            "--max-file-bytes",
            "4000000",
        ],
    )
    assert call.kwargs["browser_id"] == "browser-id"
    assert call.kwargs["signature"] == "a" * 64
    assert result["action"] == {
        "operationId": "b" * 32,
        "state": "succeeded",
        "selected": True,
        "file": {"name": "demo clip.mp4", "sizeBytes": 15, "sha256": "c" * 64},
    }
    assert result["needsVerification"] is True


@pytest.mark.parametrize(
    ("workspace", "path", "code"),
    [
        ({}, "/workspace/file.mp4", "TASK_WORKSPACE_REQUIRED"),
        ({"directory": "relative"}, "/workspace/file.mp4", "TASK_WORKSPACE_REQUIRED"),
        ({"directory": "/workspace"}, "relative.mp4", "INVALID_FILE_PATH"),
        ({"directory": "/workspace"}, "/workspace/bad\0.mp4", "INVALID_FILE_PATH"),
        ({"directory": "/workspace"}, "/elsewhere/file.mp4", "WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"),
        (
            {"directory": "/workspace"},
            "/workspace/../secret.mp4",
            "WORKSPACE_OUTSIDE_CONFIGURED_ROOTS",
        ),
        ({"directory": "/workspace"}, "/workspace", "WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"),
    ],
)
async def test_upload_rejects_unbound_or_escaped_paths_before_input(workspace, path, code):
    driver = upload_driver()
    with pytest.raises(DomainError) as error:
        await driver.act(
            {"kind": "upload", "selector": "#video", "path": path, "observationId": "observed"},
            {"workspace": workspace},
        )
    assert error.value.code == code
    driver._perform.assert_not_awaited()


def test_upload_public_cli_and_both_tool_schemas_require_selector_and_path():
    driver = upload_driver()
    registry = SimpleNamespace(registry={})
    registry.add = lambda tool: registry.registry.update({tool.name: tool})
    register_browser_tools(registry, driver)
    register_model_inputs(registry)
    tool = registry.registry["browser_act"]
    name, args = chrome_operation(
        ["upload", "#video", "/workspace/clip.mp4", "--observation", "observed"]
    )
    assert name == tool.name
    assert args == {
        "kind": "upload",
        "selector": "#video",
        "path": "/workspace/clip.mp4",
        "observationId": "observed",
    }
    tool.validate(args)
    tool.validate({key: value for key, value in args.items() if key != "observationId"})
    for field in ("path", "selector"):
        with pytest.raises(ToolArgumentsError):
            tool.validate({key: value for key, value in args.items() if key != field})
    with pytest.raises(DomainError):
        chrome_operation(["upload", "#video", "/workspace/clip.mp4", "--file-root", "/"])
