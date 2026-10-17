"""Cross-language smoke: real Go entry, catalog initialization, Python UDS and model HTTP."""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse


@pytest.fixture(scope="session")
def roami_binary(tmp_path_factory):
    if not shutil.which("go"):
        pytest.skip(
            "Go compiler unavailable; cross-language smoke requires the repository toolchain"
        )
    root = Path(__file__).resolve().parents[2]
    binary = tmp_path_factory.mktemp("roami-build") / "roami"
    subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/roami"], cwd=root, check=True, capture_output=True
    )
    return binary


async def test_go_cli_managed_runtime_round_trip(tmp_path, roami_binary):
    model_app = FastAPI()

    @model_app.post("/v1/chat/completions")
    async def model():
        text = (
            "data: "
            + json.dumps(
                {
                    "choices": [
                        {"delta": {"content": "Live transport answer"}, "finish_reason": "stop"}
                    ]
                }
            )
            + "\n\ndata: [DONE]\n\n"
        )
        return StreamingResponse(iter([text]), media_type="text/event-stream")

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    provider = uvicorn.Server(uvicorn.Config(model_app, log_level="error"))
    provider_task = asyncio.create_task(provider.serve(sockets=[listener]))
    runtime_dir = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ROAMI_", "ROAM_", "TTMUX_"))}
    env.update(
        ROAMI_HOME=str(tmp_path),
        ROAMI_DATA=str(tmp_path),
        ROAMI_CONFIG=str(tmp_path / "config.yaml"),
    )
    (tmp_path / "agent.toml").write_text(
        f'[model]\nendpoint="http://127.0.0.1:{port}/v1"\nname="injected-http-model"\n'
    )
    service = None

    async def cli(*args):
        process = await asyncio.create_subprocess_exec(
            str(roami_binary),
            "agent",
            *args,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await process.communicate()
        assert process.returncode == 0, err.decode()
        return json.loads(out)

    try:
        with tempfile.TemporaryDirectory(prefix="agent-uds-") as short_root:
            env["XDG_RUNTIME_DIR"] = short_root
            await cli("init", "--runtime-dir", str(runtime_dir))
            catalog = json.loads((tmp_path / "database/catalog.json").read_text())
            entry = next(d for d in catalog["databases"] if d["id"] == "agent-runtime")
            assert entry["state"] == "ready" and entry["path"] == "agents/runtime.db"
            service = await asyncio.create_subprocess_exec(
                str(roami_binary),
                "agent",
                "serve",
                "--runtime-dir",
                str(runtime_dir),
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(10):
                while not list(Path(short_root).rglob("*.sock")):
                    assert service.returncode is None
                    await asyncio.sleep(0.05)
            actual_socket = next(Path(short_root).rglob("*.sock"))
            assert actual_socket.stat().st_mode & 0o777 == 0o600
            created = await cli("new", "--title", "CLI round trip")
            cid = created["data"]["id"]
            await cli("send", "--conversation", cid, "--key", "one", "--text", "Hello")
            async with asyncio.timeout(5):
                while True:
                    result = await cli("history", "--conversation", cid)
                    messages = result["data"]["messages"]
                    if len(messages) == 2 and messages[-1]["status"] == "completed":
                        break
                    await asyncio.sleep(0.05)
            assert messages[-1]["content"]["text"] == "Live transport answer"
            await cli(
                "notify", "--conversation", cid, "--key", "reminder-1", "--text", "Time to review"
            )
            after = await cli("history", "--conversation", cid)
            assert after["data"]["messages"][-1]["content"]["text"] == "Time to review"
            # Python holds the same lock domain used by unified database maintenance.
            busy = await asyncio.create_subprocess_exec(
                str(roami_binary),
                "db",
                "backup",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await busy.communicate()
            assert busy.returncode != 0 and b"STORAGE_BUSY" in err
    finally:
        if service:
            # The CLI child shares its parent process group. Terminate Python via its private socket PID owner.
            import signal

            children_file = Path(f"/proc/{service.pid}/task/{service.pid}/children")
            if children_file.exists():
                for child in children_file.read_text().split():
                    os.kill(int(child), signal.SIGTERM)
            try:
                await asyncio.wait_for(service.wait(), 5)
            except TimeoutError:
                service.kill()
                await service.wait()
        provider.should_exit = True
        await provider_task
