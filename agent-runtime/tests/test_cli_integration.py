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


async def test_go_coding_execution_tmux_replay_cancel_and_unknown(tmp_path, roami_binary):
    """Real isolated tmux and Go runners; fake agent binaries avoid paid/account calls."""
    import shlex

    if not shutil.which("tmux"):
        pytest.skip("tmux required for coding executor integration")
    binary_dir = tmp_path / "bin with 'quotes"
    binary_dir.mkdir()
    calls = tmp_path / "calls"
    for kind in ["codex", "claude"]:
        agent = binary_dir / kind
        agent.write_text(
            "#!/bin/sh\n"
            + f"printf '%s\\n' {shlex.quote(kind)} >> {shlex.quote(str(calls))}\n"
            + 'prompt=$(cat)\ncase "$prompt" in\n'
            + "  slow*) sleep 30;;\n"
            + '  fail*) printf "intentional stderr" >&2; exit 7;;\n'
            + 'esac\nprintf "Answer: %s" "$prompt"\n'
        )
        agent.chmod(0o755)
    tmux_socket = "roami-execution-" + tmp_path.name + "-" + str(os.getpid())
    wrapper = binary_dir / "tmux"
    actual_tmux = shutil.which("tmux")
    wrapper.write_text(
        f'#!/bin/sh\nexec {shlex.quote(actual_tmux)} -L {shlex.quote(tmux_socket)} "$@"\n'
    )
    wrapper.chmod(0o755)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ROAMI_", "ROAM_", "TTMUX_")) and k != "TMUX"
    }
    env.update(
        ROAMI_HOME=str(tmp_path / "home"),
        ROAMI_DATA=str(tmp_path / "home"),
        TMUX_BIN=str(wrapper),
        PATH=str(binary_dir) + os.pathsep + os.environ["PATH"],
    )

    async def cli(sub, *args, spec=None, success=True):
        p = await asyncio.create_subprocess_exec(
            str(roami_binary),
            "agent",
            "execution",
            sub,
            *args,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await p.communicate(json.dumps(spec).encode() if spec else b"")
        if success:
            assert p.returncode == 0, err.decode()
            return json.loads(out)
        assert p.returncode != 0
        return err.decode()

    async def finished(key):
        async with asyncio.timeout(15):
            while True:
                result = await cli("status", "--key", key)
                if result.get("result"):
                    return result
                await asyncio.sleep(0.05)

    try:
        for kind in ["codex", "claude"]:
            spec = {
                "key": kind,
                "executor": kind,
                "directory": str(binary_dir),
                "prompt": "literal $(touch SHOULD_NOT_EXIST) `uname` ' 中文\nnext line",
                "timeoutSeconds": 20,
            }
            first = await cli("launch", "--file", "-", spec=spec)
            assert first["session"]
            result = await finished(kind)
            assert result["result"]["state"] == "succeeded"
            assert result["result"]["summary"] == "Answer: " + spec["prompt"]
            assert not (binary_dir / "SHOULD_NOT_EXIST").exists()
            assert await cli("launch", "--file", "-", spec=spec) == result
            assert "LAUNCH_KEY_CONFLICT" in await cli(
                "launch", "--file", "-", spec={**spec, "prompt": "different"}, success=False
            )
        assert calls.read_text().splitlines() == ["codex", "claude"]
        slow = {
            "key": "slow",
            "executor": "codex",
            "directory": str(binary_dir),
            "prompt": "slow please",
            "timeoutSeconds": 20,
        }
        await cli("launch", "--file", "-", spec=slow)
        cancelled = await cli("cancel", "--key", "slow")
        assert cancelled["state"] == "cancelling"
        assert (await finished("slow"))["state"] == "cancelled"
        failed = {**slow, "key": "failure", "prompt": "fail please"}
        await cli("launch", "--file", "-", spec=failed)
        result = await finished("failure")
        assert result["result"]["exitCode"] == 7
        assert result["result"]["stderr"] == "intentional stderr"
        unknown = {**slow, "key": "unknown"}
        live = await cli("launch", "--file", "-", spec=unknown)
        await asyncio.to_thread(
            subprocess.run, [str(wrapper), "kill-session", "-t", "=" + live["session"]], check=True
        )
        observed = await cli("status", "--key", "unknown")
        assert observed["state"] in {"unknown", "failed"}
        before_retry = calls.read_text()
        retried = await cli("launch", "--file", "-", spec=unknown)
        assert retried["state"] in {"unknown", "failed"}
        assert calls.read_text() == before_retry
    finally:
        await asyncio.to_thread(
            subprocess.run, [str(wrapper), "kill-server"], capture_output=True, check=False
        )
