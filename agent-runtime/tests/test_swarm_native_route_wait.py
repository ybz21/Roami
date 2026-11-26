"""Temporary native model failure preserves the original coordination queue."""

import json
import sqlite3

import pytest
from test_native_main import fixture_binding, stopped
from test_runtime import ConversationModel
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_coordination import delegated_team as delegated_team_fixture

from roami_agent.app import Runtime
from roami_agent.storage.database import Database, row
from roami_agent.storage.swarm_coordination import admitted_batch
from roami_okr.native_main import NativeMain

coordination = coordination_fixture
delegated_team = delegated_team_fixture


@pytest.mark.parametrize("code", ["MODEL_ROUTE_NO_AVAILABLE_MEMBER", "CLAUDE_COMPACTION_FAILED"])
async def test_confirmed_no_output_route_failure_resumes_the_same_batch(
    coordination, monkeypatch, code
):
    runtime, _, team, _, post, _ = coordination
    first = await post()
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    binding = {
        **fixture_binding(),
        "conversation_id": turn["conversation_id"],
        "owner_id": turn["owner_id"],
    }
    launches = []

    async def command(sub, *args, spec=None):
        assert sub == "launch"
        launches.append(spec)
        return stopped(binding, state="failed") | {
            "result": {
                "state": "failed",
                "inputStopped": True,
                "outcomeKnown": True,
                "errorCode": code,
                "stopEvidenceSha256": "e" * 64,
            },
        }

    runtime.loop.model = NativeMain(binding, turn, command)
    await runtime.loop.run(turn, "main")
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (turn["id"],)
        )
    )
    assert job["state"] == "queued"
    assert json.loads(job["payload_json"]) == {
        "coordinationBatchId": batch["batchId"],
        "nativeRouteRetry": 1,
    }
    evidence = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT payload_json FROM events WHERE kind='turn.deferred' AND turn_id=?",
            (turn["id"],),
        )
    )
    assert json.loads(evidence["payload_json"]) == {
        "turnId": turn["id"],
        "reason": code,
        "retryAtMs": job["available_ms"],
        "retryGeneration": 1,
        "stopEvidenceSha256": "e" * 64,
    }
    snapshot = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    assert snapshot["mainModelWait"] == {"retryAtMs": job["available_ms"]}
    assert await claim(runtime, batch) is None
    monkeypatch.setattr("roami_agent.conversation.mailbox.now_ms", lambda: job["available_ms"])
    next_turn = await claim(runtime, batch)
    assert next_turn["id"] == turn["id"] and next_turn["lease_epoch"] > turn["lease_epoch"]
    assert next_turn["native_route_retry"] == 1
    assert not await runtime.journal.defer_native_route(turn, code, "e" * 64)
    retained = await runtime.db.call(
        lambda db: admitted_batch(db, "alice", turn["id"], lease_epoch=next_turn["lease_epoch"])
    )
    assert retained["id"] == batch["batchId"] and retained["inputs"][0]["postId"] == first["id"]

    async def recovered(sub, *args, spec=None):
        assert sub == "launch"
        launches.append(spec)
        return stopped(binding)

    snapshot = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    assert snapshot["mainModelWait"] is None
    runtime.loop.model = NativeMain(binding, next_turn, recovered)
    assert await runtime.loop.run(next_turn, "main") == "Actual native answer"
    actual = await runtime.db.call(
        lambda db: row(db, "SELECT state FROM turns WHERE id=?", (turn["id"],))
    )
    assert actual == {"state": "completed"}
    assert launches[1]["key"].endswith(":retry-1")
    assert launches[0]["sessionId"] == launches[1]["sessionId"] == binding["session_id"]
    assert launches[0]["preparedFrom"] == launches[1]["preparedFrom"] == binding["launch_key"]


async def test_unverified_or_noncurrent_turn_cannot_enter_route_retry(coordination):
    runtime, _, team, _, post, _ = coordination
    await post()
    turn = await claim(runtime, await queue(runtime, team))
    code = "MODEL_ROUTE_NO_AVAILABLE_MEMBER"
    assert not await runtime.journal.defer_native_route(turn, code, "")
    assert not await runtime.journal.defer_native_route(
        {**turn, "trigger_kind": "user"}, code, "e" * 64
    )
    assert not await runtime.journal.defer_native_route({**turn, "lease_epoch": 0}, code, "e" * 64)

    message_id = await runtime.journal.start(turn)
    await runtime.db.call(
        lambda db: db.execute(
            "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,"
            "effect,state,idempotency_key,created_ms,updated_ms) "
            "VALUES('earlier-tool',?,?,'delegate','{}','write','succeeded','earlier-tool',1,1)",
            (turn["id"], message_id),
        ),
        write=True,
    )
    assert not await runtime.journal.defer_native_route(turn, code, "e" * 64)


async def test_restart_preserves_retry_deadline(coordination, monkeypatch, tmp_path):
    runtime, _, team, _, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    assert await runtime.journal.defer_native_route(
        turn, "MODEL_ROUTE_NO_AVAILABLE_MEMBER", "a" * 64
    )
    snapshot = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    deadline = snapshot["mainModelWait"]["retryAtMs"]
    isolated_root = tmp_path / "restarted"
    isolated_root.mkdir()
    path = isolated_root / "runtime.db"

    def backup(source):
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()

    await runtime.db.call(backup)
    database = Database(path, isolated_root, managed=False)
    await database.open()
    restarted = Runtime(database, ConversationModel())
    try:
        await restarted.conversations.recover()
        snapshot = await restarted.swarms.snapshot("alice", team["id"], include_memory=False)
        assert snapshot["mainModelWait"] == {"retryAtMs": deadline}
        assert await claim(restarted, batch) is None
        monkeypatch.setattr("roami_agent.conversation.mailbox.now_ms", lambda: deadline)
        resumed = await claim(restarted, batch)
        assert resumed["id"] == turn["id"] and resumed["native_route_retry"] == 1
        assert resumed["lease_epoch"] > turn["lease_epoch"]
    finally:
        await restarted.close()
        await database.close()


async def test_dispatch_pause_preserves_a_proven_retry_without_claiming_it(
    coordination, monkeypatch
):
    runtime, _, team, _, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)

    async def control(action):
        value = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
        await runtime.swarms.control(
            "alice",
            team["id"],
            {"action": action, "expectedRevision": value["revision"], "commandKey": action},
        )

    await control("pause")
    assert await runtime.journal.defer_native_route(
        turn, "MODEL_ROUTE_NO_AVAILABLE_MEMBER", "a" * 64
    )
    value = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    assert value["paused"] and value["mainModelWait"] is None
    job = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT available_ms FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
            (turn["id"],),
        )
    )
    now = job["available_ms"]
    monkeypatch.setattr("roami_agent.conversation.mailbox.now_ms", lambda: now)
    assert await claim(runtime, batch) is None
    await control("resume")
    now += 1000
    resumed = await claim(runtime, batch)
    assert resumed["id"] == turn["id"] and resumed["native_route_retry"] == 1
