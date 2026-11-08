"""Real scheduler admission across native/CLI jobs sharing a physical directory."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from roami_agent.dispatch.scheduler import Scheduler
from roami_agent.dispatch.workspace_queue import directory_key


class QueueDatabase:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            "CREATE TABLE jobs(id,kind,aggregate_id,payload_json,state,available_ms);"
            "CREATE TABLE turns(id,branch_id,trigger_kind);"
            "CREATE TABLE branches(id);"
            "CREATE TABLE tasks(id,revision,state,target_json,intent_json);"
            "CREATE TABLE task_attempts(id,task_id,task_revision,executor_kind,native_branch_id);"
        )

    async def call(self, operation, **kwargs):
        return operation(self.connection)

    def add(self, name, directory, *, executor="native", state="queued", workspace="one"):
        target = (
            {
                "nodeId": "local",
                "workspace": {"directory": str(directory), "workspaceId": workspace},
            }
            if directory
            else None
        )
        self.connection.execute(
            "INSERT INTO tasks VALUES(?,1,?,?,?)", (name, state, json.dumps(target), "{}")
        )
        self.connection.execute(
            "INSERT INTO task_attempts VALUES(?,?,1,?,NULL)", (name, name, executor)
        )
        if state == "queued":
            self.connection.execute(
                "INSERT INTO jobs VALUES(?,'task.run',?,?,'queued',0)",
                (name, name, json.dumps({"runId": name})),
            )


class Admission:
    def __init__(self):
        self.db = QueueDatabase()
        self.release = asyncio.Event()
        self.started = []
        self.active = {}
        self.scheduler = Scheduler(
            self.db,
            SimpleNamespace(workers=8, main_concurrency=2),
            None,
            SimpleNamespace(tasks=SimpleNamespace(revisions=SimpleNamespace(advance=AsyncMock()))),
            None,
            None,
            asyncio.Event(),
            self.active,
            None,
        )
        self.scheduler._job = self.run

    async def run(self, job):
        self.started.append(job["id"])
        await self.release.wait()

    async def scan(self):
        await self.scheduler._scan()
        await asyncio.sleep(0)

    async def close(self):
        handles = [item["handle"] for item in self.active.values()]
        self.release.set()
        await asyncio.gather(*handles)
        await asyncio.sleep(0)
        self.db.connection.close()


@pytest.mark.asyncio
async def test_original_jobs_wait_for_native_and_detached_cli(tmp_path):
    queue = Admission()
    try:
        queue.db.add("data", tmp_path, state="running")
        queue.db.add("x", tmp_path, executor="cli", workspace="different-id")
        queue.db.add("bili", tmp_path, executor="cli")
        await queue.scan()
        assert queue.started == []
        queue.db.connection.execute("UPDATE tasks SET state='succeeded' WHERE id='data'")
        await queue.scan()
        assert queue.started == ["x"]
        queue.db.connection.execute("UPDATE tasks SET state='running' WHERE id='x'")
        queue.db.connection.execute("UPDATE jobs SET state='done' WHERE id='x'")
        queue.release.set()
        await asyncio.gather(*(item["handle"] for item in queue.active.values()))
        await asyncio.sleep(0)
        await queue.scan()
        assert queue.started == ["x"]
        assert tuple(
            queue.db.connection.execute("SELECT id,state FROM jobs WHERE id='bili'").fetchone()
        ) == ("bili", "queued")
        queue.db.connection.execute("UPDATE tasks SET state='succeeded' WHERE id='x'")
        await queue.scan()
        assert queue.started == ["x", "bili"]
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_symlink_serializes_but_other_directories_run(tmp_path):
    alias = tmp_path / "alias"
    actual = tmp_path / "actual"
    actual.mkdir()
    alias.symlink_to(actual, target_is_directory=True)
    queue = Admission()
    try:
        queue.db.add("first", actual)
        queue.db.add("alias", alias, executor="cli")
        queue.db.add("other", tmp_path / "other")
        await queue.scan()
        assert queue.started == ["first", "other"]
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_live_unresolved_preparation_waits_but_legacy_unknown_does_not(tmp_path):
    queue = Admission()
    try:
        queue.db.add("legacy", None, state="running")
        queue.db.add("resolving", None)
        queue.db.add("next", tmp_path / "next")
        await queue.scan()
        assert queue.started == ["resolving"]
        queue.db.connection.execute(
            "UPDATE tasks SET state='preparing',target_json=? WHERE id='resolving'",
            (json.dumps({"nodeId": "local", "workdir": str(tmp_path / "resolved")}),),
        )
        await queue.scan()
        assert queue.started == ["resolving", "next"]
        assert (
            queue.db.connection.execute("SELECT state FROM tasks WHERE id='legacy'").fetchone()[0]
            == "running"
        )
    finally:
        await queue.close()


def test_directory_scope_and_invalid_targets(tmp_path):
    def key(value):
        return directory_key({"target_json": json.dumps(value)})

    assert key({"nodeId": "remote", "workdir": str(tmp_path)}) != key({"workdir": str(tmp_path)})
    assert key({"workdir": "relative"}) is None
    assert directory_key({"target_json": "{"}) is None
    assert directory_key({"intent_json": json.dumps({"target": {"directory": str(tmp_path)}})}) == (
        "local",
        str(tmp_path),
    )
