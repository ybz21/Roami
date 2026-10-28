"""Host execution does not depend on command names or borrow task workspaces."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from test_foundations import call
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows


@pytest.mark.parametrize(
    "argv", [["ps", "-p", str(os.getpid()), "-o", "pid="], ["df", "-k"], ["uname", "-s"]]
)
async def test_host_operations_execute_without_a_workspace_or_task(store, argv):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=()))
    try:
        result = await runtime.tools.invoke(
            call("bash", {"argv": argv, "scope": "host"}), "main", {"owner": "alice"}
        )
        assert result["exitCode"] == 0 and result["stdout"].strip()
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


async def test_arbitrary_program_and_pipeline_use_disposable_cwd_and_filter_credentials(
    store, tmp_path, monkeypatch
):
    binary = tmp_path / "probe"
    binary.write_text("#!/bin/sh\nprintf custom-program")
    binary.chmod(0o700)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "foreign-repository"))
    monkeypatch.setenv("PROBE_PROVIDER_SECRET", "ephemeral-fixture")
    settings = Settings(shell_roots=())
    monkeypatch.setattr(
        Settings, "provider_key_environments", lambda self: {"PROBE_PROVIDER_SECRET"}
    )
    runtime = Runtime(store, ConversationModel(), settings=settings)
    try:
        result = await runtime.tools.invoke(
            call("bash", {"command": f"{binary} | tr a-z A-Z", "scope": "host"}),
            "main",
            {"owner": "alice"},
        )
        assert result["stdout"] == "CUSTOM-PROGRAM"
        result = await runtime.tools.invoke(
            call(
                "bash",
                {
                    "scope": "host",
                    "argv": [
                        sys.executable,
                        "-c",
                        (
                            "import os; from pathlib import Path; "
                            "assert 'GIT_DIR' not in os.environ; assert 'PROBE_PROVIDER_SECRET' not in os.environ; "
                            "Path('scratch').write_text('temporary'); print(os.getcwd())"
                        ),
                    ],
                },
            ),
            "main",
            {"owner": "alice"},
        )
        directory = Path(result["stdout"].strip())
        assert directory.name.startswith("roami-host-") and not directory.exists()
        assert not (Path.cwd() / "scratch").exists()
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "role,binding,args,error",
    [
        ("research", {}, {}, "HOST_SCOPE_UNAVAILABLE"),
        ("worker", {}, {}, "HOST_SCOPE_UNAVAILABLE"),
        ("main", {"taskId": "unprepared"}, {}, "HOST_SCOPE_UNAVAILABLE"),
        ("main", {"workspace": {"directory": "/tmp"}}, {}, "HOST_SCOPE_UNAVAILABLE"),
        ("main", {}, {"cwd": "/tmp"}, "HOST_SCOPE_CWD_NOT_ALLOWED"),
        ("main", {}, {"cwd": ""}, "HOST_SCOPE_CWD_NOT_ALLOWED"),
        (
            "main",
            {},
            {"argv": ["roami", "agent", "host", "processes", "--input", "{}"]},
            "HOST_SCOPE_REGISTERED_COMMAND",
        ),
        ("main", {}, {"scope": "unknown"}, "INVALID_TOOL_ARGUMENTS"),
    ],
)
async def test_host_scope_is_explicit_and_cannot_override_role_or_workspace(
    store, monkeypatch, role, binding, args, error
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Rejected host operation started a process")

    monkeypatch.setattr("roami_agent.tools.shell.execute", forbidden)
    runtime = Runtime(store, ConversationModel())
    try:
        with pytest.raises(DomainError, match=error):
            await runtime.tools.invoke(
                call("bash", {"scope": "host", "argv": ["echo", "probe"], **args}), role, binding
            )
    finally:
        await runtime.close()


async def test_host_scope_retains_disable_policy_and_large_output_ownership(store):
    runtime = Runtime(store, ConversationModel())
    wire = call("bash", {"scope": "host", "argv": [sys.executable, "-c", "print('x'*20000)"]})
    try:
        runtime.tools.disabled_tools.add("bash")
        with pytest.raises(DomainError, match="TOOL_DISABLED"):
            await runtime.tools.invoke(wire, "main", {"owner": "alice"})
        runtime.tools.disabled_tools.clear()
        tool, _ = runtime.tools.validate(wire, "main")
        assert tool.effect == "write" and tool.cancellation_stops_execution
        result = await runtime.tools.invoke(wire, "main", {"owner": "alice"})
        assert result["exitCode"] == 0 and result["outputExternalized"]
        reference = result["artifactRefs"][0]
        assert (await runtime.artifacts.read("alice", reference["id"]))[1] == b"x" * 20000 + b"\n"
        with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
            await runtime.artifacts.read("bob", reference["id"])
    finally:
        await runtime.close()


@pytest.mark.parametrize("cancel", [False, True])
async def test_host_failure_or_cancellation_cleans_working_directory_and_child_process(
    store, tmp_path, cancel
):
    marker = tmp_path / "started.json"
    program = (
        "import json,os,time; from pathlib import Path; "
        f"marker=Path({str(marker)!r}); pending=marker.with_suffix('.tmp'); "
        "pending.write_text(json.dumps([os.getpid(),os.getcwd()])); pending.replace(marker); "
        + ("time.sleep(60)" if cancel else "raise SystemExit(7)")
    )
    runtime = Runtime(store, ConversationModel())
    running = asyncio.create_task(
        runtime.tools.invoke(
            call("bash", {"scope": "host", "argv": [sys.executable, "-c", program]}),
            "main",
            {"owner": "alice"},
        )
    )
    try:
        async with asyncio.timeout(10):
            while not marker.exists():
                await asyncio.sleep(0.01)
        pid, directory = json.loads(marker.read_text())
        if cancel:
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            assert (await running)["exitCode"] == 7
        assert not Path(directory).exists()
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await runtime.close()


@pytest.mark.parametrize("argv", [["uname", "-s"], ["df", "-k"]])
async def test_main_recovers_generically_and_records_actual_scope_without_delegation(store, argv):
    class Main:
        model = "host-scope-fixture"
        step = 0

        async def stream(self, messages, tools):
            self.step += 1
            if self.step == 1:
                args = {"argv": argv}
            elif self.step == 2:
                failure = json.loads(messages[-1]["content"])
                assert failure["error"] == "WORKSPACE_REQUIRED"
                assert "scope=host" in failure["recovery"]
                assert "host,processes" not in failure["recovery"]
                args = {"argv": argv, "scope": "host"}
            else:
                result = json.loads(messages[-1]["content"])
                assert result["exitCode"] == 0 and result["stdout"].strip()
                yield ModelEvent(
                    "tool",
                    {**call("reply", {"text": "Local operation completed."}), "id": "answer"},
                )
                return
            yield ModelEvent("tool", {**call("bash", args), "id": str(self.step)})

    runtime = Runtime(store, Main(), memory_model=ConversationModel())
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", conversation["id"], "host", "Check the current machine"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        calls = await store.call(
            lambda db: rows(
                db,
                "SELECT tool_name,effect,state,arguments_json FROM tool_calls WHERE turn_id=? ORDER BY rowid",
                (receipt["turnId"],),
            )
        )
        assert [(item["tool_name"], item["effect"], item["state"]) for item in calls] == [
            ("bash", "write", "failed"),
            ("bash", "write", "succeeded"),
            ("reply", "read", "succeeded"),
        ]
        assert json.loads(calls[1]["arguments_json"])["scope"] == "host"
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


async def test_role_catalogs_expose_host_scope_only_to_main(store):
    runtime = Runtime(store, ConversationModel())
    try:
        schemas = {
            role: next(
                item["function"]["parameters"]["properties"]
                for item in runtime.tools.catalog(role)
                if item["function"]["name"] == "bash"
            )
            for role in ("main", "worker", "research")
        }
        assert schemas["main"]["scope"]["enum"] == ["workspace", "host"]
        assert schemas["worker"]["scope"]["enum"] == ["workspace"]
        assert schemas["research"] == schemas["worker"]
    finally:
        await runtime.close()
