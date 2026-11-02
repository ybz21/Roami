"""Cross-language smoke: real Go entry, catalog initialization, Python UDS and model HTTP."""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
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


async def test_python_artifacts_survive_real_go_backup_and_restore(tmp_path, roami_binary):
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.storage.artifact_store import ArtifactStore
    from roami_agent.storage.database import Database

    source, target = tmp_path / "source", tmp_path / "restored"
    source.mkdir()
    runtime_dir = Path(__file__).resolve().parents[1]
    base_env = {
        k: v for k, v in os.environ.items() if not k.startswith(("ROAMI_", "ROAM_", "TTMUX_"))
    }

    async def cli(root, *args):
        env = dict(
            base_env,
            ROAMI_HOME=str(root),
            ROAMI_DATA=str(root),
            ROAMI_CONFIG=str(root / "config.yaml"),
        )
        process = await asyncio.create_subprocess_exec(
            str(roami_binary),
            *args,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await process.communicate()
        assert process.returncode == 0, err.decode()
        return json.loads(out)

    await cli(source, "agent", "init", "--runtime-dir", str(runtime_dir))
    database = Database(source / "database/agents/runtime.db", source)
    await database.open()
    artifacts = ArtifactStore(database)
    try:
        conversation = await Conversations(database).create("alice")
        accepted = await Conversations(database).accept(
            "alice", conversation["id"], "evidence", "Keep evidence"
        )
        reference = await artifacts.put(
            "alice",
            b"exact binary\x00\xff",
            mime_type="application/octet-stream",
            message_id=accepted["messageId"],
            metadata={"source": "fixture"},
        )
    finally:
        await artifacts.close()
        await database.close()
    backup = await cli(source, "db", "backup")
    await cli(target, "db", "restore", backup)
    restored = Database(target / "database/agents/runtime.db", target)
    await restored.open()
    artifacts = ArtifactStore(restored)
    try:
        actual, body = await artifacts.read("alice", reference["id"])
        assert actual == reference and body == b"exact binary\x00\xff"
        history = await Conversations(restored).messages("alice", conversation["id"])
        assert history["messages"][0]["id"] == reference["messageId"]
    finally:
        await artifacts.close()
        await restored.close()


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
        return StreamingResponse(
            iter([text]),
            media_type="text/event-stream",
            headers={"X-Request-Id": "fixture-cli-response"},
        )

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
            env["ROAMI_DATA"] = short_root
            env["XDG_RUNTIME_DIR"] = "/unused-interactive-runtime-dir"
            await cli("init", "--runtime-dir", str(runtime_dir))
            catalog = json.loads((Path(short_root) / "database/catalog.json").read_text())
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
                while True:
                    assert service.returncode is None
                    try:
                        await cli("status")
                        break
                    except AssertionError:
                        await asyncio.sleep(0.05)
            actual_socket = next(Path(short_root).rglob("agent-*.sock"))
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
            usage = await cli("gateway", "usage")
            call = usage["data"]["recent"][0]
            assert call["model"] == "injected-http-model"
            assert call["priceStatus"] == "unpriced" and call["cost"] is None
            assert call["state"] == "unknown"
            assert call["upstreamHttpStatus"] == 200
            assert call["upstreamRequestId"] == "fixture-cli-response"
            await cli(
                "notify", "--conversation", cid, "--key", "reminder-1", "--text", "Time to review"
            )
            after = await cli("history", "--conversation", cid)
            assert after["data"]["messages"][-1]["content"]["text"] == "Time to review"
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(actual_socket)), base_url="http://agent"
            ) as client:
                task = await client.post(
                    "/v1/tasks",
                    headers={"X-Roami-Owner": "local"},
                    json={
                        "conversationId": cid,
                        "requestKey": "control-list-task",
                        "goal": "Return a read-only analysis",
                    },
                )
            assert task.status_code == 202
            tid = task.json()["data"]["id"]
            controls = await cli("control", "ls", "--task", tid)
            assert controls["data"]["taskId"] == tid and controls["data"]["resources"] == []
            operation = await cli(
                "steer",
                "--task",
                tid,
                "--revision",
                "1",
                "--key",
                "continued-cli",
                "--text",
                "Include another check",
            )
            async with asyncio.timeout(5):
                while True:
                    steering = await cli(
                        "steering", "--task", tid, "--operation", operation["data"]["operationId"]
                    )
                    if steering["data"]["state"] != "stopping":
                        break
                    await asyncio.sleep(0.05)
            assert steering["data"]["state"] == "applied" and steering["data"]["revision"] == 2
            scheduled = await cli(
                "reminder",
                "add",
                "--conversation",
                cid,
                "--key",
                "clock-once",
                "--text",
                "Scheduled CLI reminder",
                "--after-seconds",
                "1",
            )
            again = await cli(
                "reminder",
                "add",
                "--conversation",
                cid,
                "--key",
                "clock-once",
                "--text",
                "Scheduled CLI reminder",
                "--after-seconds",
                "1",
            )
            assert again["data"]["id"] == scheduled["data"]["id"]
            async with asyncio.timeout(5):
                while True:
                    history = await cli("history", "--conversation", cid)
                    matching = [
                        item
                        for item in history["data"]["messages"]
                        if item["content"].get("text") == "Scheduled CLI reminder"
                    ]
                    if matching:
                        break
                    await asyncio.sleep(0.05)
            assert len(matching) == 1
            daily = await cli(
                "reminder",
                "add",
                "--conversation",
                cid,
                "--key",
                "daily-cli",
                "--text",
                "Daily check",
                "--daily-at",
                "09:00",
                "--timezone",
                "Asia/Shanghai",
            )
            assert (await cli("reminder", "ls"))["data"][0]["id"] == daily["data"]["id"]
            await cli("reminder", "cancel", "--id", daily["data"]["id"])
            brief = await cli(
                "reminder",
                "add",
                "--kind",
                "daily_brief",
                "--conversation",
                cid,
                "--key",
                "daily-brief-cli",
                "--text",
                "Summarize yesterday's recorded work",
                "--daily-at",
                (datetime.now(UTC) + timedelta(minutes=5)).strftime("%H:%M"),
                "--timezone",
                "UTC",
            )
            assert brief["data"]["id"].startswith("brief:")
            listed = (await cli("reminder", "ls"))["data"]
            assert (
                next(item for item in listed if item["id"] == brief["data"]["id"])["spec"]["kind"]
                == "daily_brief"
            )
            await cli("reminder", "cancel", "--id", brief["data"]["id"])
            preferences = (await cli("notification-preferences", "get"))["data"]
            preferences["quietHours"] = {"start": "22:00", "end": "08:00"}
            settings_file = tmp_path / "notification-settings.json"
            settings_file.write_text(json.dumps(preferences))
            assert (await cli("notification-preferences", "set", "--file", str(settings_file)))[
                "data"
            ] == preferences
            assert (await cli("notification-preferences", "get"))["data"] == preferences
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


async def test_go_coding_execution_tmux_replay_cancel_and_unknown(
    tmp_path, roami_binary, monkeypatch, store
):
    """Real isolated tmux and Go runners; fake agent binaries avoid paid/account calls."""
    import shlex
    import sqlite3

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
            + "  slow*|*'slow delegated task'*) sleep 30;;\n"
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
        ROAMI_DATABASE_DIR=str(tmp_path / "home/database"),
        ROAMI_BACKUP_DIR=str(tmp_path / "home/backups"),
        ROAMI_CONFIG=str(tmp_path / "home/config.yaml"),
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
                "title": "修复报告链接",
                "directory": str(binary_dir),
                "prompt": "literal $(touch SHOULD_NOT_EXIST) `uname` ' 中文\nnext line",
                "timeoutSeconds": 20,
            }
            first = await cli("launch", "--file", "-", spec=spec)
            assert first["session"]
            result = await finished(kind)
            assert result["result"]["state"] == "succeeded"
            assert result["result"]["summary"] == "Answer: " + spec["prompt"]
            with sqlite3.connect(tmp_path / "home/database/meta.db") as metadata:
                label = metadata.execute(
                    "SELECT label FROM sessions WHERE id=?", (first["session"],)
                ).fetchone()[0]
            assert label == "修复报告链接"
            assert not (binary_dir / "SHOULD_NOT_EXIST").exists()
            assert await cli("launch", "--file", "-", spec=spec) == result
            assert "LAUNCH_KEY_CONFLICT" in await cli(
                "launch", "--file", "-", spec={**spec, "prompt": "different"}, success=False
            )
        assert calls.read_text().splitlines() == ["codex", "claude"]

        from roami_agent.app import Runtime
        from roami_agent.executors.roami_cli import CodingExecutor
        from roami_agent.protocol.models import ModelEvent
        from roami_agent.server.configuration import Settings
        from roami_agent.storage.database import row

        for name, value in env.items():
            monkeypatch.setenv(name, value)
        settings = Settings(cli_bin=str(roami_binary), coding_directory=binary_dir)

        class ResultModel:
            model = "injected-result-model"

            async def stream(self, messages, tools):
                yield ModelEvent("text", "Coding result received in its original conversation.")

        async def verifier(task, result):
            return result["exitCode"] == 0 and result["summary"].endswith("resume delegated task")

        def runtime():
            return Runtime(
                store,
                ResultModel(),
                settings=settings,
                executor=CodingExecutor(store, settings, persistent=False),
                verifier=verifier,
            )

        agent_runtime = runtime()
        await agent_runtime.start()
        try:
            origin = await agent_runtime.conversations.create("alice")
            other = await agent_runtime.conversations.create("alice")
            delegated = await agent_runtime.tasks.create(
                "alice",
                origin["id"],
                "resume delegated task",
                key="runtime-restart",
                executor="claude",
                record_intent=True,
            )
            async with asyncio.timeout(15):
                while not await store.call(
                    lambda db: row(
                        db,
                        "SELECT session_id FROM task_attempts WHERE task_id=? AND session_id IS NOT NULL",
                        (delegated["id"],),
                    )
                ):
                    await asyncio.sleep(0.02)
            await agent_runtime.close()
            # The coding process survives a Python restart; the same launch is observed.
            agent_runtime = runtime()
            await agent_runtime.start()
            async with asyncio.timeout(15):
                while not await store.call(
                    lambda db: row(
                        db,
                        "SELECT id FROM turns WHERE conversation_id=? AND trigger_kind='completion' AND state='completed'",
                        (origin["id"],),
                    )
                ):
                    await asyncio.sleep(0.02)
            original_messages = await agent_runtime.conversations.messages("alice", origin["id"])
            assert original_messages["messages"][-1]["content"]["text"].startswith("Coding result")
            assert not (await agent_runtime.conversations.messages("alice", other["id"]))[
                "messages"
            ]
            completed = await agent_runtime.tasks.list("alice", origin["id"])
            assert completed[0]["state"] == "succeeded"
            assert calls.read_text().splitlines().count("claude") == 2
            cancelling = await agent_runtime.tasks.create(
                "alice",
                origin["id"],
                "slow delegated task",
                key="runtime-cancel",
                executor="codex",
                record_intent=True,
            )
            async with asyncio.timeout(15):
                while not await store.call(
                    lambda db: row(
                        db,
                        "SELECT session_id FROM task_attempts WHERE task_id=? AND session_id IS NOT NULL",
                        (cancelling["id"],),
                    )
                ):
                    await asyncio.sleep(0.02)
            await agent_runtime.tasks.cancel("alice", cancelling["id"])
            async with asyncio.timeout(15):
                while not await store.call(
                    lambda db: row(
                        db,
                        "SELECT id FROM tasks WHERE id=? AND state='cancelled'",
                        (cancelling["id"],),
                    )
                ):
                    await asyncio.sleep(0.02)
        finally:
            await agent_runtime.close()
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


async def test_existing_legacy_codex_receives_main_message_through_real_go_cli(
    tmp_path, roami_binary, monkeypatch, store
):
    import asyncio
    import os
    import shlex
    import shutil
    import subprocess
    import sys

    from test_runtime import until

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.server.configuration import Settings
    from roami_agent.storage.database import row

    tmux = shutil.which("tmux")
    if not tmux:
        pytest.skip("tmux required")
    socket = "roami-main-message-" + tmp_path.name + "-" + str(os.getpid())
    wrapper = tmp_path / "tmux"
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(tmux)} -L {shlex.quote(socket)} "$@"\n')
    wrapper.chmod(0o700)
    received = tmp_path / "received.txt"
    receiver = tmp_path / "receiver.py"
    receiver.write_text(
        f'import pathlib,time\nprint("legacy ready",flush=True)\npathlib.Path({str(received)!r}).write_text(input())\ntime.sleep(15)\n'
    )
    name = "2026-1018-1935-0001"
    for key in list(os.environ):
        if key.startswith(("ROAMI_", "ROAM_", "TTMUX_")) or key == "TMUX":
            monkeypatch.delenv(key)
    monkeypatch.setenv("TMUX_BIN", str(wrapper))
    monkeypatch.setenv("ROAMI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ROAMI_DATA", str(tmp_path / "home"))
    monkeypatch.setenv("ROAMI_CONFIG", str(tmp_path / "config.yaml"))
    await asyncio.to_thread(
        subprocess.run,
        [
            tmux,
            "-L",
            socket,
            "-f",
            "/dev/null",
            "new-session",
            "-d",
            "-s",
            name,
            "-c",
            str(tmp_path),
            shlex.join([sys.executable, str(receiver)]) + "; sleep 15",
        ],
        check=True,
    )
    await asyncio.to_thread(
        subprocess.run,
        [tmux, "-L", socket, "set-option", "-t", "$0", "@roam_name", "Legacy Codex"],
        check=True,
    )

    class Model:
        model = "go-send-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                yield ModelEvent("text", "Delivered to existing Codex")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "legacy",
                        "function": {
                            "name": "delegate",
                            "arguments": json.dumps(
                                {
                                    "requestComplete": False,
                                    "goal": "Fix the layout",
                                    "executor": "codex",
                                    "target": {"kind": "session", "sessionId": name},
                                }
                            ),
                        },
                    },
                )

    runtime = Runtime(store, Model(), settings=Settings(cli_bin=str(roami_binary)))
    try:
        async with asyncio.timeout(5):
            while b"legacy ready" not in await asyncio.to_thread(
                subprocess.check_output,
                [tmux, "-L", socket, "capture-pane", "-p", "-t", "$0"],
            ):
                await asyncio.sleep(0.05)
        await runtime.start()
        c = await runtime.conversations.create("alice")
        sent = await runtime.chat.submit("alice", c["id"], "send", "Send the fix to Legacy Codex")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (sent["turnId"],)
            ),
            timeout=10,
        )
        async with asyncio.timeout(3):
            while not received.exists():
                await asyncio.sleep(0.05)
        assert received.read_text() == "Fix the layout"
        view = await runtime.conversations.messages("alice", c["id"])
        assert any(item["kind"] == "tool" for item in view["activities"])
        events = await runtime.conversations.events("alice", view["conversation"]["id"])
        delivery = next(
            e["payload"]["activity"]
            for e in events
            if e["kind"] == "tool.completed"
            and e["payload"].get("activity", {}).get("state") == "delivered"
        )
        assert delivery["state"] == "delivered"
        assert (
            await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 0
        )
    finally:
        await runtime.close()
        await asyncio.to_thread(
            subprocess.run, [tmux, "-L", socket, "kill-server"], check=False, capture_output=True
        )
