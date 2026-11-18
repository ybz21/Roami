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
            "CREATE TABLE turns(id,branch_id,trigger_kind,owner_id,conversation_id,state);"
            "CREATE TABLE branches(id);"
            "CREATE TABLE conversations(id,owner_id);"
            "CREATE TABLE tasks(id,revision,state,target_json,intent_json);"
            "CREATE TABLE task_attempts(id,task_id,task_revision,executor_kind,native_branch_id);"
            "CREATE TABLE project_okr_mains(owner_id,project_id,conversation_id);"
            "CREATE TABLE project_okr_main_providers(owner_id,project_id,conversation_id,generation,binding_json);"
            "CREATE TABLE swarm_members(id,current_work_id,execution_generation);"
            "CREATE TABLE swarm_member_work(member_id,work_id);"
            "CREATE TABLE swarm_work_items(id,task_id,execution_generation,executor,model);"
            "CREATE TABLE swarm_member_provider_generations(member_id,generation,executor,model,binding_json);"
        )

    def main(self, name, directory, *, state="queued", native=True):
        cid, branch = name + "-conversation", name + "-branch"
        self.connection.execute("INSERT INTO branches VALUES(?)", (branch,))
        self.connection.execute("INSERT INTO conversations VALUES(?,'alice')", (cid,))
        self.connection.execute(
            "INSERT INTO turns VALUES(?,?,'user','alice',?,?)", (name, branch, cid, state)
        )
        if native:
            self.connection.execute(
                "INSERT INTO project_okr_mains VALUES('alice',?,?)", (name, cid)
            )
            self.connection.execute(
                "INSERT INTO project_okr_main_providers VALUES('alice',?,?,1,?)",
                (name, cid, json.dumps({"directory": str(directory)})),
            )
        if state == "queued":
            self.connection.execute(
                "INSERT INTO jobs VALUES(?,'turn.run',?,'{}','queued',0)", (name, name)
            )

    def pin(self, task, directory):
        member, work = task + "-member", task + "-work"
        self.connection.execute("INSERT INTO swarm_members VALUES(?,?,2)", (member, work))
        self.connection.execute("INSERT INTO swarm_member_work VALUES(?,?)", (member, work))
        self.connection.execute(
            "INSERT INTO swarm_work_items VALUES(?,?,2,'claude','free')", (work, task)
        )
        self.connection.execute(
            "INSERT INTO swarm_member_provider_generations VALUES(?,2,'claude','free',?)",
            (member, json.dumps({"directory": str(directory)})),
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


@pytest.mark.asyncio
async def test_native_main_reserves_directory_before_member_target_preparation(tmp_path):
    queue = Admission()
    try:
        queue.db.main("main", tmp_path)
        queue.db.add("x", None, executor="cli")
        queue.db.pin("x", tmp_path)
        queue.db.add("bili", None, executor="cli")
        queue.db.pin("bili", tmp_path)
        queue.db.add("other", tmp_path / "elsewhere", executor="cli")
        await queue.scan()
        assert queue.started == ["main", "other"]
        assert (
            queue.db.connection.execute("SELECT state FROM tasks WHERE id='x'").fetchone()[0]
            == "queued"
        )
        assert (
            queue.db.connection.execute("SELECT state FROM jobs WHERE id='bili'").fetchone()[0]
            == "queued"
        )
        queue.db.connection.execute("UPDATE jobs SET state='done' WHERE id IN ('main','other')")
        queue.db.connection.execute("UPDATE turns SET state='completed' WHERE id='main'")
        queue.release.set()
        await asyncio.gather(*(item["handle"] for item in queue.active.values()))
        await asyncio.sleep(0)
        await queue.scan()
        assert queue.started == ["main", "other", "x"]
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_native_main_waits_for_worker_but_home_main_stays_available(tmp_path):
    queue = Admission()
    try:
        queue.db.add("active", tmp_path, state="running", executor="cli")
        queue.db.main("project-main", tmp_path)
        queue.db.main("home-main", None, native=False)
        queue.db.add("other", tmp_path / "elsewhere")
        await queue.scan()
        assert queue.started == ["home-main", "other"]
        queue.db.connection.execute("UPDATE tasks SET state='succeeded' WHERE id='active'")
        await queue.scan()
        assert queue.started == ["home-main", "other", "project-main"]
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_running_native_main_is_occupied_without_an_in_memory_handle(tmp_path):
    queue = Admission()
    try:
        queue.db.main("detached-main", tmp_path, state="running")
        queue.db.add("data", None, executor="cli")
        queue.db.pin("data", tmp_path)
        await queue.scan()
        assert queue.started == []
        queue.db.connection.execute("UPDATE turns SET state='completed' WHERE id='detached-main'")
        await queue.scan()
        assert queue.started == ["data"]
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_native_main_and_pinned_member_resolve_the_same_physical_directory(tmp_path):
    actual, alias = tmp_path / "actual", tmp_path / "alias"
    actual.mkdir()
    alias.symlink_to(actual, target_is_directory=True)
    queue = Admission()
    try:
        queue.db.main("main", actual)
        queue.db.add("ops", None, executor="cli")
        queue.db.pin("ops", alias)
        await queue.scan()
        assert queue.started == ["main"]
    finally:
        await queue.close()
