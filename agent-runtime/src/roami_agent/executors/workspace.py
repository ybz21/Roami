"""Long-lived Go workspace lease; EOF never asserts that native tools stopped."""

import asyncio
import json
import math
import os
import signal
from contextlib import asynccontextmanager

from roami_agent.executors.project import provision_project
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded


@asynccontextmanager
async def hold_workspace(settings, task, run, *, stopped=None):
    target = json.loads(task["intent_json"])["target"]
    if target["kind"] == "new_project":
        target = await provision_project(settings, task, run)
    if target.get("nodeId", "local") != "local":
        raise DomainError("NATIVE_NODE_UNAVAILABLE")
    if "workspaceId" in target and (
        not isinstance(target["workspaceId"], str) or not target["workspaceId"]
    ):
        raise DomainError("INVALID_NATIVE_WORKSPACE_TARGET")
    spec = {
        "key": run["launch_id"],
        "executor": "native",
        "timeoutSeconds": max(
            1, math.ceil((json.loads(task["budget_json"])["deadlineMs"] - now_ms()) / 1000)
        ),
    }
    if target["kind"] == "project":
        if not target.get("projectId") or target.get("directory"):
            raise DomainError("INVALID_NATIVE_PROJECT_TARGET")
        spec.update(projectId=target["projectId"])
        for name in ["workspaceId", "base", "remote"]:
            if target.get(name):
                spec[name] = target[name]
    elif target["kind"] == "new_session" and (target.get("directory") or settings.coding_directory):
        spec["directory"] = str(target.get("directory") or settings.coding_directory)
    else:
        raise DomainError("NATIVE_TARGET_ADAPTER_NOT_IMPLEMENTED")
    process = await asyncio.create_subprocess_exec(
        settings.cli_bin,
        "agent",
        "execution",
        "hold",
        "--file",
        "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        env={
            name: value
            for name, value in os.environ.items()
            if name not in settings.provider_key_environments()
        },
    )
    state, confirmed = "failed", True
    try:
        process.stdin.write((encoded(spec) + "\n").encode())
        await process.stdin.drain()
        async with asyncio.timeout(min(125, spec["timeoutSeconds"])):
            line = await process.stdout.readline()
        try:
            receipt = json.loads(line)
            workspace = receipt["workspace"]
            if (
                receipt["state"] != "native_running"
                or not isinstance(workspace, dict)
                or not isinstance(workspace.get("directory"), str)
                or not os.path.isabs(workspace["directory"])
                or not workspace.get("workspaceId")
            ):
                raise ValueError("invalid workspace receipt")
        except (ValueError, KeyError, TypeError) as exc:
            raise DomainError("NATIVE_WORKSPACE_UNAVAILABLE") from exc
        try:
            yield workspace
            state = "succeeded"
        except asyncio.CancelledError:
            state = "cancelled"
            raise
        except DomainError as exc:
            confirmed = exc.code not in {"TOOL_OUTCOME_UNKNOWN", "MCP_OUTCOME_UNKNOWN"}
            raise
        except BaseException:
            confirmed = False
            raise
        finally:
            if stopped is not None:
                confirmed = confirmed and await stopped()
            if not confirmed:
                raise DomainError("NATIVE_WORKSPACE_OUTCOME_UNKNOWN")
            if confirmed:

                async def release():
                    process.stdin.write(
                        (encoded({"state": state, "stopped": True}) + "\n").encode()
                    )
                    await process.stdin.drain()
                    answer = json.loads(await process.stdout.readline())
                    if answer.get("released") is not True:
                        raise DomainError("NATIVE_WORKSPACE_RELEASE_UNKNOWN")
                    await process.wait()

                try:
                    async with asyncio.timeout(5):
                        await release()
                except (OSError, ValueError, TimeoutError) as exc:
                    raise DomainError("NATIVE_WORKSPACE_RELEASE_UNKNOWN") from exc
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await process.wait()
