"""Timeouts keep committed tool evidence without making a partial run complete."""

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest

from roami_agent.improvement.evaluation.behavior_review import review_trial
from roami_agent.improvement.evaluation.execution import containers
from roami_agent.improvement.evaluation.execution.interrupted_evidence import snapshot_program
from roami_agent.improvement.evaluation.protocol_suite import protocol_suite
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


def runtime_database(path, *, count=3, long=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE messages(id TEXT PRIMARY KEY, content_json TEXT);
    CREATE TABLE tool_calls(id TEXT PRIMARY KEY, tool_name TEXT, state TEXT, arguments_json TEXT,
      created_ms INTEGER, result_message_id TEXT);
    CREATE TABLE tasks(id TEXT PRIMARY KEY,state TEXT,revision INTEGER,created_ms INTEGER);
    """)
    for i in range(count):
        state = "running" if i == count - 1 else "succeeded"
        args = json.dumps({"command": "x" * 5000 + str(i)}) if long else '{"path":"input.json"}'
        db.execute(
            "INSERT INTO tool_calls VALUES(?,?,?,?,?,NULL)",
            (str(i), "bash" if i else "read", state, args, i),
        )
    db.execute("INSERT INTO tasks VALUES('task','running',1,0)")
    db.commit()
    return db


def extract(path):
    result = subprocess.run(
        [sys.executable, "-c", snapshot_program(path)], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("state", ["planned", "running"])
def test_reader_keeps_wal_commits_and_marks_inflight_tools_unknown(tmp_path, state):
    path = tmp_path / "runtime.db"
    db = runtime_database(path)
    db.execute("UPDATE tool_calls SET state=? WHERE id='2'", (state,))
    db.commit()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        value = extract(path)
        after = hashlib.sha256(path.read_bytes()).hexdigest()
    finally:
        db.close()
    assert value["source"] == "interrupted_runtime_snapshot" and value["complete"] is False
    assert value["recorded_tool_calls"] == value["captured_tool_calls"] == 3
    assert value["tool_calls"][-1]["state"] == "unknown"
    assert value["tool_calls"][-1]["recorded_state"] == state
    assert before == after


def test_long_arguments_and_record_limits_are_explicit(tmp_path):
    path = tmp_path / "runtime.db"
    db = runtime_database(path, count=2001, long=True)
    try:
        value = extract(path)
    finally:
        db.close()
    assert value["truncated"] is True and value["recorded_tool_calls"] == 2001
    assert 0 < value["captured_tool_calls"] <= 2000
    assert len(json.dumps(value).encode()) < 8_000_000
    first, second = value["tool_calls"][:2]
    assert first["arguments_json_truncated"] is True
    assert first["arguments_json"] != second["arguments_json"]


@pytest.mark.parametrize("partial_log", [False, True])
async def test_timeout_recovers_tools_and_preserves_the_primary_failure(
    tmp_path, monkeypatch, partial_log
):
    async def docker(*args, **kwargs):
        if args[0] == "start":
            db = runtime_database(tmp_path / "state/runtime.db")
            db.close()
            if partial_log:
                (tmp_path / "state/execution-log.json").write_text("{partial")
            raise TimeoutError
        return b""

    async def remove(*args):
        pass

    async def sandbox(state, program, **kwargs):
        assert kwargs["copy_workspace"] is True and kwargs["timeout"] == 15
        return json.dumps(await asyncio.to_thread(extract, state / "runtime.db")).encode()

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(Settings())
    executor.image_id = "fixture-image"
    monkeypatch.setattr(executor, "remove", remove)
    monkeypatch.setattr(executor, "sandbox", sandbox)
    case = protocol_suite()["cases"][0]
    result = await executor.run(case, {}, tmp_path)
    assert result["grade"]["reason"] == "RSI_TIME_BUDGET" and not result["grade"]["passed"]
    assert result["metrics"]["elapsed_ms"] is None and result["metrics"]["right_censored"]
    summary = trial_summary(case, result, tmp_path)
    assert summary["tool_calls"] == len(summary["tools"]) == 3
    assert summary["execution_evidence"]["complete"] is False
    assert summary["tools"][-1]["state"] == "unknown"
    log = review_trial(result, tmp_path)
    assert log["complete"] is False
    assert any(
        e["file"] == "interrupted-execution-log.json" and e["coverage"] == "interrupted"
        for e in log["logs"]
    )


async def test_recovery_failure_does_not_replace_the_original_timeout(tmp_path, monkeypatch):
    async def docker(*args, **kwargs):
        if args[0] == "start":
            (tmp_path / "state/runtime.db").write_bytes(b"broken database")
            (tmp_path / "state/execution-log.json").write_text("{partial")
            raise TimeoutError
        return b""

    async def remove(*args):
        pass

    async def fail(*args, **kwargs):
        raise DomainError("RSI_DOCKER_COMMAND_FAILED")

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(Settings())
    executor.image_id = "fixture-image"
    monkeypatch.setattr(executor, "remove", remove)
    monkeypatch.setattr(executor, "sandbox", fail)
    case = protocol_suite()["cases"][0]
    result = await executor.run(case, {}, tmp_path)
    assert result["grade"]["reason"] == "RSI_TIME_BUDGET"
    summary = trial_summary(case, result, tmp_path)
    assert summary["tool_calls"] is None
    assert summary["execution_evidence"]["error"] == "RSI_DOCKER_COMMAND_FAILED"


async def test_existing_complete_log_is_preserved_without_recovery(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    (state / "execution-log.json").write_text('{"tool_calls":[],"traces":[]}')

    async def forbidden(*args, **kwargs):
        pytest.fail("A complete log must not be replayed")

    executor = containers.ContainerExecutor(Settings())
    monkeypatch.setattr(executor, "sandbox", forbidden)
    await executor.recover_execution(state, tmp_path)
    assert not (tmp_path / "interrupted-execution-log.json").exists()


async def test_symlink_database_or_log_cannot_read_host_data(tmp_path, monkeypatch):
    state = tmp_path / "case/state"
    state.mkdir(parents=True)
    outside = tmp_path / "private.json"
    outside.write_text('{"tool_calls":[{"tool_name":"private"}]}')
    (state / "runtime.db").symlink_to(outside)
    (state / "execution-log.json").symlink_to(outside)

    async def forbidden(*args, **kwargs):
        pytest.fail("Symlinked runtime database must not be opened")

    executor = containers.ContainerExecutor(Settings())
    monkeypatch.setattr(executor, "sandbox", forbidden)
    await executor.recover_execution(state, state.parent)
    value = trial_summary({"id": "case"}, {"grade": {"passed": False}, "metrics": {}}, state.parent)
    assert value["tools"] == [] and value["tool_calls"] is None


def test_execution_log_symlink_cannot_expose_outside_tool_records(tmp_path):
    root = tmp_path / "case"
    (root / "state").mkdir(parents=True)
    outside = tmp_path / "other-owner.json"
    outside.write_text(
        json.dumps({"tool_calls": [{"tool_name": "private_action", "state": "succeeded"}]})
    )
    (root / "state/execution-log.json").symlink_to(outside)
    value = trial_summary({"id": "case"}, {"grade": {"passed": False}, "metrics": {}}, root)
    assert value["tools"] == [] and value["tool_calls"] is None


async def test_real_readonly_container_extracts_wal_without_changing_source(tmp_path):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image or not shutil.which("docker"):
        pytest.skip("Frozen Docker image required")
    executor = containers.ContainerExecutor(Settings(), image=image)
    try:
        await executor.preflight()
    except (DomainError, OSError):
        pytest.skip("Frozen Docker image required")
    state = tmp_path / "state"
    state.mkdir()
    db = runtime_database(state / "runtime.db")
    files = [state / name for name in ("runtime.db", "runtime.db-wal")]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    try:
        await executor.recover_execution(state, tmp_path)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    finally:
        db.close()
    assert after == before
    value = json.loads((tmp_path / "interrupted-execution-log.json").read_text())
    assert value["recorded_tool_calls"] == 3 and value["complete"] is False
