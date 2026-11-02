"""Installation fences and the real Go-owned runtime lifecycle use disposable instances."""

import asyncio
import json
import os
import signal
from pathlib import Path

import httpx
import pytest
from test_cli_integration import roami_binary  # noqa: F401
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.server.http import create_app


async def test_installation_fence_preserves_pending_work_and_rejects_busy_upgrade(store):
    runtime = Runtime(store, ConversationModel())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://agent",
            headers={"X-Roami-Owner": "local"},
        ) as client:
            runtime.active["running-task"] = {"kind": "task.run"}
            busy = await client.post("/internal/installation/quiesce", json={"resume": False})
            assert busy.status_code == 409
            assert not runtime.settings.updating
            runtime.active.clear()
            paused = await client.post("/internal/installation/quiesce", json={"resume": False})
            assert paused.status_code == 200
            assert runtime.settings.updating
            rejected = await client.post("/v1/conversations", json={"title": "pending"})
            assert rejected.status_code == 503
            assert rejected.json()["error"]["code"] == "AGENT_UPGRADE_IN_PROGRESS"
            assert (await client.get("/v1/model-settings")).status_code == 200
            forbidden = await client.post(
                "/internal/installation/quiesce",
                headers={"X-Roami-Owner": "other"},
                json={"resume": True},
            )
            assert forbidden.status_code == 403
            assert runtime.settings.updating
            assert (
                await client.post("/internal/installation/quiesce", json={"resume": True})
            ).status_code == 200
            assert not runtime.settings.updating
            assert (
                await client.post("/v1/conversations", json={"title": "pending"})
            ).status_code == 201
    finally:
        await runtime.close()


@pytest.mark.parametrize("crash_parent", [False, True])
async def test_go_supervisor_restarts_child_and_closes_it_when_parent_exits(
    tmp_path,
    roami_binary,  # noqa: F811
    crash_parent,
):
    repo = Path(__file__).resolve().parents[2]
    launcher = ["bash", str(repo / "scripts/dev/isolated-roami.sh"), str(tmp_path)]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ROAMI_", "ROAM_", "TTMUX_"))
    }
    env["ROAMI_AGENT_RUNTIME"] = str(repo / "agent-runtime")
    (tmp_path / "config.yaml").write_text("web:\n  bind: 127.0.0.1:0\n  tls: false\n")

    async def cli(*args):
        process = await asyncio.create_subprocess_exec(
            *launcher,
            str(roami_binary),
            *args,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await process.communicate()
        return process.returncode, out, err

    async def status(previous=None):
        async with asyncio.timeout(30):
            while True:
                code, out, _ = await cli("agent", "status")
                if code == 0:
                    data = json.loads(out)["data"]
                    if previous is None or data["pid"] != previous:
                        return data
                await asyncio.sleep(0.1)

    child = None
    with (tmp_path / "supervisor.log").open("w") as log:
        process = await asyncio.create_subprocess_exec(
            *launcher, str(roami_binary), "server", env=env, stdout=log, stderr=log
        )
        try:
            initial = await status()
            assert initial["managed"]
            child = initial["pid"]
            os.kill(child, signal.SIGKILL)
            restarted = await status(child)
            child = restarted["pid"]
            assert restarted["managed"]
            process.send_signal(signal.SIGKILL if crash_parent else signal.SIGTERM)
            await asyncio.wait_for(process.wait(), 20)
            async with asyncio.timeout(20):
                while True:
                    try:
                        os.kill(child, 0)
                    except ProcessLookupError:
                        break
                    # A reparented zombie is stopped; PID 1 reaping is outside this process.
                    stat = Path(f"/proc/{child}/stat")
                    if stat.exists() and stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                        break
                    await asyncio.sleep(0.1)
        finally:
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.wait(), 20)
            cleanup = await asyncio.create_subprocess_exec(
                *launcher,
                "--stop",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await cleanup.communicate()
            assert cleanup.returncode == 0


def test_runtime_includes_timezone_data_without_host_zoneinfo():
    import zoneinfo
    from zoneinfo import ZoneInfo, reset_tzpath

    previous = zoneinfo.TZPATH
    try:
        reset_tzpath([])
        ZoneInfo.clear_cache()
        assert ZoneInfo("UTC").key == "UTC"
        assert ZoneInfo("Asia/Shanghai").key == "Asia/Shanghai"
    finally:
        reset_tzpath(previous)
        ZoneInfo.clear_cache()
