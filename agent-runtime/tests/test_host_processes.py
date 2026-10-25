"""Host inspection never borrows a coding workspace or a browser research profile."""

import json
from pathlib import Path

import pytest
from test_foundations import call
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row, rows
from roami_agent.tools.host_processes import linux_memory, process_rows

PS_OUTPUT = """10 1 125.0 2.0 1024 02:00 cpu worker
20 1 5.0 9.0 4096 1-02:00:00 /usr/bin/memory-worker
30 1 0.0 0.0 0 00:01 idle
"""


def host_call(args=None):
    return call(
        "bash", {"argv": ["roami", "agent", "host", "processes", "--input", json.dumps(args or {})]}
    )


def test_process_parser_handles_names_units_and_malformed_samples():
    processes, skipped = process_rows(
        PS_OUTPUT + "bad row\n40 1 nan 0 1 00:01 bad\n50 1 0 0 -1 00:01 bad\n"
    )
    assert skipped == 3
    assert processes[0] == {
        "pid": 10,
        "parentPid": 1,
        "name": "cpu worker",
        "cpuPercent": 125.0,
        "memoryPercent": 2.0,
        "rssBytes": 1048576,
        "elapsed": "02:00",
    }
    assert processes[1]["name"] == "memory-worker"


@pytest.mark.parametrize("content", ["MemTotal: invalid", "", "MemTotal: 1 kB\nMemAvailable: 2 kB"])
def test_missing_memory_stays_unknown(monkeypatch, content):
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: content)
    assert linux_memory() is None


def test_linux_memory_uses_available_and_reports_swap(monkeypatch):
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: (
            "MemTotal: 100 kB\nMemAvailable: 60 kB\nSwapTotal: 20 kB\nSwapFree: 5 kB\n"
        ),
    )
    assert linux_memory() == {
        "totalBytes": 102400,
        "availableBytes": 61440,
        "usedBytes": 40960,
        "swapTotalBytes": 20480,
        "swapUsedBytes": 15360,
    }


async def test_diagnostics_are_discoverable_read_only_and_need_no_workspace(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    calls = []

    async def ps(argv, **kwargs):
        calls.append((argv, kwargs))
        return {"exitCode": 0, "stdout": PS_OUTPUT, "stderr": ""}

    monkeypatch.setattr("roami_agent.tools.host_processes.execute", ps)
    monkeypatch.setattr("roami_agent.tools.host_processes.linux_memory", lambda: None)
    monkeypatch.setattr("os.getloadavg", lambda: (1.0, 2.0, 3.0))
    try:
        for query in ["machine process system status node", "进程占用", "本机内存负载"]:
            items = runtime.tools.directory.list(query, "cli", 20, "main")["items"]
            assert any(
                command["argv"] == ["roami", "agent", "host", "processes", "--input", "JSON"]
                for item in items
                for command in item.get("commands", [])
            )
        for role in ["main", "worker"]:
            tool, _ = runtime.tools.validate(host_call(), role)
            assert tool.name == "host_processes" and tool.effect == "read"
            result = await runtime.tools.invoke(host_call({"limit": 1}), role, {})
            assert result["scope"] == "runtime_host"
            assert result["topCpu"][0]["pid"] == 10
            assert result["topMemory"][0]["pid"] == 20
            assert len(result["topCpu"]) == len(result["topMemory"]) == 1
            assert result["processCount"] == 3
            assert result["memory"] is None and result["unavailable"] == ["memory"]
            assert result["loadAverage"] == [1.0, 2.0, 3.0]
            assert result["cpuPercentBasis"] == "ps_lifetime_average_per_core"
        assert calls[0][0] == ["ps", "-axo", "pid=,ppid=,pcpu=,pmem=,rss=,etime=,comm="]
        assert calls[0][1]["timeout"] == 5
        assert set(calls[0][1]["env"]) == {"PATH", "LC_ALL"}
        assert "cwd" not in calls[0][1]
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "args", [{"limit": 0}, {"limit": 51}, {"argv": ["kill", "10"]}, {"cwd": "/tmp"}]
)
async def test_host_diagnostics_cannot_become_a_shell(store, args):
    runtime = Runtime(store, ConversationModel())
    try:
        with pytest.raises(DomainError, match="INVALID_TOOL_ARGUMENTS"):
            await runtime.tools.invoke(host_call(args), "main", {})
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await runtime.tools.invoke(host_call(), "research", {})
        assert not any(
            command["argv"][1:4] == ["agent", "host", "processes"]
            for item in runtime.tools.directory.list("", "cli", 20, "research")["items"]
            for command in item.get("commands", [])
        )
        runtime.tools.disabled_tools.add("bash")
        with pytest.raises(DomainError, match="TOOL_DISABLED"):
            await runtime.tools.invoke(call("host_processes", {}), "main", {})
    finally:
        await runtime.close()


@pytest.mark.parametrize("failure", ["exit", "empty", "missing", "timeout"])
async def test_collection_failure_does_not_claim_an_empty_healthy_machine(
    store, monkeypatch, failure
):
    async def failed_ps(*args, **kwargs):
        if failure == "missing":
            raise FileNotFoundError
        if failure == "timeout":
            raise TimeoutError
        return {"exitCode": 1 if failure == "exit" else 0, "stdout": "", "stderr": "private"}

    monkeypatch.setattr("roami_agent.tools.host_processes.execute", failed_ps)
    runtime = Runtime(store, ConversationModel())
    try:
        with pytest.raises(DomainError, match="HOST_DIAGNOSTICS_UNAVAILABLE"):
            await runtime.tools.invoke(host_call(), "main", {})
    finally:
        await runtime.close()


async def test_main_recovers_from_ps_rejection_without_delegating_or_borrowing_a_workspace(
    store, monkeypatch
):
    class Main:
        model = "host-diagnostics-fixture"
        step = 0

        async def stream(self, messages, tools):
            self.step += 1
            if self.step == 1:
                wire = call("bash", {"argv": ["ps", "aux", "--sort=-%cpu"]})
            elif self.step == 2:
                error = json.loads(messages[-1]["content"])
                assert error["error"] == "WORKSPACE_REQUIRED"
                assert "host,processes" in error["recovery"]
                wire = host_call()
            else:
                result = json.loads(messages[-1]["content"])
                assert result["topCpu"][0]["pid"] == 10
                wire = call("reply", {"text": "已读取本机快照，CPU 排名第一的是 cpu worker。"})
            yield ModelEvent("tool", {**wire, "id": f"host-{self.step}"})

    async def ps(*args, **kwargs):
        return {"exitCode": 0, "stdout": PS_OUTPUT, "stderr": ""}

    monkeypatch.setattr("roami_agent.tools.host_processes.execute", ps)
    runtime = Runtime(store, Main(), memory_model=ConversationModel())
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", conversation["id"], "host", "帮我看下当前机器的进程占用情况"
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
                "SELECT tool_name,effect,state FROM tool_calls WHERE turn_id=? ORDER BY rowid",
                (receipt["turnId"],),
            )
        )
        assert calls == [
            {"tool_name": "bash", "effect": "write", "state": "failed"},
            {"tool_name": "host_processes", "effect": "read", "state": "succeeded"},
            {"tool_name": "reply", "effect": "read", "state": "succeeded"},
        ]
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()
