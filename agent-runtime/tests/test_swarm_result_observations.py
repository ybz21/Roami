"""A handoff, a host result, and an actual model read are distinct facts."""

import json
import sqlite3

import pytest
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture
from test_swarm_delegations import finish

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_coordination import admitted_batch
from roami_agent.storage.swarm_coordination_results import status_evidence

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def report(runtime, actor, *, known=True):
    result = {
        "state": "succeeded" if known else "failed",
        "summary": "Actual current evidence" if known else "Outcome not yet known",
        "inputStopped": known,
        "outcomeKnown": known,
    }
    if known:
        await runtime.tasks.report("alice", actor["taskId"], actor["runId"], 1, result)
    else:
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE tasks SET state='running' WHERE id=?", (actor["taskId"],)
            ),
            write=True,
        )
        task = await runtime.db.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
        )
        run = await runtime.db.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],))
        )
        await runtime.dispatch.complete(task, run, result, "interrupted", unknown=True)
        callback = await runtime.db.call(
            lambda db: row(
                db,
                "SELECT kind,aggregate_id FROM jobs WHERE dedupe_key=?",
                ("task.completion:" + actor["runId"] + ":interrupted",),
            )
        )
        if callback["kind"] == "turn.run":
            await finish(runtime, await claim(runtime, {"turnId": callback["aggregate_id"]}))
    return result


async def observations(runtime):
    return await runtime.db.call(lambda db: rows(db, "SELECT * FROM swarm_result_observations"))


async def build(runtime, turn):
    runtime.loop.context.swarms = runtime.loop.context.remembered = None
    return await runtime.loop.context.build(turn, "Base instructions", [], None)


async def status(runtime, turn, actor, *, cli=False, include_result=True):
    source = await runtime.journal.origin(turn)
    mid = await runtime.journal.start(turn)
    call = {
        "id": "read-current",
        "function": {
            "name": "task_status",
            "arguments": json.dumps({"taskId": actor["taskId"], "includeResult": include_result}),
        },
    }
    if cli:
        call["function"] = {
            "name": "bash",
            "arguments": json.dumps(
                {
                    "argv": [
                        "roami",
                        "agent",
                        "capability",
                        "call",
                        "task_status",
                        "--input",
                        call["function"]["arguments"],
                    ]
                }
            ),
        }
    await runtime.journal.finish(turn, mid, "", [call], None, 1, final=False, completion=None)
    await runtime.gateway.invoke(
        turn,
        mid,
        call,
        "main",
        {
            "owner": "alice",
            "conversation": turn["conversation_id"],
            "turnId": turn["id"],
            "leaseEpoch": turn["lease_epoch"],
            "originMessageId": source["id"],
            "toolCallId": call["id"],
        },
    )


async def test_handoff_cannot_swallow_a_later_result_of_the_same_run(coordination):
    runtime, _, team, _, post, actor = coordination
    await post("handoff", "handoff")
    first = await queue(runtime, team)
    first_turn = await claim(runtime, first)
    result = await report(runtime, actor)
    frozen = await runtime.db.call(lambda db: admitted_batch(db, "alice", first["turnId"]))
    assert frozen["results"] == [] and len(frozen["inputs"]) == 1
    await finish(runtime, first_turn)
    second = await queue(runtime, team)
    current = await runtime.db.call(lambda db: admitted_batch(db, "alice", second["turnId"]))
    assert current["inputs"] == [] and current["results"][0]["result"] == result
    assert current["results"][0]["runId"] == actor["runId"]
    await finish(runtime, await claim(runtime, second))
    assert await queue(runtime, team) is None


async def test_frozen_unknown_keeps_its_bytes_and_known_result_gets_a_new_batch(coordination):
    runtime, _, team, _, _, actor = coordination
    unknown = await report(runtime, actor, known=False)
    first = await queue(runtime, team)
    turn = await claim(runtime, first)
    known = await report(runtime, actor)
    original = await runtime.db.call(lambda db: admitted_batch(db, "alice", turn["id"]))
    assert original["results"][0]["result"] == unknown
    await finish(runtime, turn)
    second = await queue(runtime, team)
    current = await runtime.db.call(lambda db: admitted_batch(db, "alice", second["turnId"]))
    assert current["results"][0]["result"] == known
    assert (
        original["results"][0]["executionReceipt"]["receiptId"]
        != current["results"][0]["executionReceipt"]["receiptId"]
    )


async def test_preview_does_not_observe_but_actual_manifest_records_result_identity(coordination):
    runtime, _, team, enabled, _, actor = coordination
    await report(runtime, actor)
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    await runtime.journal.start(turn)
    plan, prompt = await build(runtime, turn)
    assert "Actual current evidence" in json.dumps(prompt)
    assert not await observations(runtime)
    await runtime.manifests.record(turn, 1, "fixture", "wire", plan, [], "main")
    facts = await observations(runtime)
    assert len(facts) == 1 and facts[0]["delegation_id"] == enabled["delegationId"]
    source = json.loads(facts[0]["source_json"])
    assert source == {"kind": "coordination_batch", "batchId": batch["batchId"]}
    manifest = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM prompt_manifests WHERE id=?", (facts[0]["manifest_id"],))
    )
    assert manifest["turn_id"] == turn["id"]


@pytest.mark.parametrize("cli", [False, True])
async def test_late_result_read_in_real_task_status_only_counts_in_the_next_request(
    coordination, cli
):
    runtime, _, team, _, post, actor = coordination
    await post()
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    await report(runtime, actor)
    await status(runtime, turn, actor, cli=cli)
    assert not await observations(runtime)
    plan, prompt = await build(runtime, turn)
    assert len(plan["executionResultEvidence"]) == 1
    assert any(
        item.get("role") == "tool" and "executionReceipt" in str(item.get("content"))
        for item in prompt
    )
    await runtime.manifests.record(turn, 1, "fixture", "wire", plan, [], "main")
    actual = await observations(runtime)
    assert len(actual) == 1 and json.loads(actual[0]["source_json"])["kind"] == "task_status"
    await finish(runtime, turn)
    assert await queue(runtime, team) is None


@pytest.mark.parametrize("change", ["absent", "truncated", "failed", "invented_call", "forgotten"])
async def test_missing_or_untrusted_tool_content_does_not_observe_a_result(coordination, change):
    runtime, _, team, _, post, actor = coordination
    await post()
    turn = await claim(runtime, await queue(runtime, team))
    await report(runtime, actor)
    await status(runtime, turn, actor)
    _, prompt = await build(runtime, turn)
    actual = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM tool_calls WHERE turn_id=? AND tool_name='task_status'",
            (turn["id"],),
        )
    )
    if change == "absent":
        prompt = [item for item in prompt if item.get("role") != "tool"]
    elif change == "truncated":
        prompt = [
            {**item, "content": str(item.get("content"))[:20]}
            if item.get("role") == "tool"
            else item
            for item in prompt
        ]
    elif change == "invented_call":
        prompt = [
            {**item, "tool_call_id": "invented"} if item.get("role") == "tool" else item
            for item in prompt
        ]
    elif change == "failed":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE tool_calls SET state='failed' WHERE id=?", (actual["id"],)
            ),
            write=True,
        )
    else:
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
                (actual["result_message_id"],),
            ),
            write=True,
        )
    assert await runtime.db.call(lambda db: status_evidence(db, turn, prompt)) == []
    assert not await observations(runtime)


async def test_result_dedup_does_not_drop_a_new_member_question(coordination):
    runtime, _, team, _, post, actor = coordination
    await report(runtime, actor)
    first = await queue(runtime, team)
    await finish(runtime, await claim(runtime, first))
    await post("new-question")
    second = await queue(runtime, team)
    value = await runtime.db.call(lambda db: admitted_batch(db, "alice", second["turnId"]))
    assert value["results"] == [] and value["inputs"][0]["text"].endswith("new-question")


async def test_failed_observation_insert_rolls_back_manifest_and_read_receipts(coordination):
    runtime, _, team, _, post, actor = coordination
    await post()
    await report(runtime, actor)
    turn = await claim(runtime, await queue(runtime, team))
    await runtime.journal.start(turn)
    plan, _ = await build(runtime, turn)
    await runtime.db.call(
        lambda db: db.execute(
            "CREATE TRIGGER reject_observation BEFORE INSERT ON swarm_result_observations BEGIN SELECT RAISE(ABORT,'observation failure'); END"
        ),
        write=True,
    )
    with pytest.raises(sqlite3.IntegrityError, match="observation failure"):
        await runtime.manifests.record(turn, 1, "fixture", "wire", plan, [], "main")
    assert not await observations(runtime)
    assert not await runtime.db.call(
        lambda db: row(db, "SELECT id FROM prompt_manifests WHERE turn_id=?", (turn["id"],))
    )
    assert (await runtime.swarms.inbox("alice", team["id"], {}))["items"][0]["readMs"] is None


@pytest.mark.parametrize("change", ["stop", "lease", "source"])
async def test_result_observation_cannot_bypass_current_context(coordination, change):
    runtime, _, team, _, _, actor = coordination
    await report(runtime, actor)
    turn = await claim(runtime, await queue(runtime, team))
    await runtime.journal.start(turn)
    plan, _ = await build(runtime, turn)
    if change == "stop":
        await runtime.chat.interrupt("alice", team["mainConversationId"], "stop")
    elif change == "lease":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (turn["id"],)
            ),
            write=True,
        )
    else:
        source = await runtime.db.call(
            lambda db: row(db, "SELECT origin_message_id FROM tasks WHERE id=?", (actor["taskId"],))
        )
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
                (source["origin_message_id"],),
            ),
            write=True,
        )
    with pytest.raises(DomainError):
        await runtime.manifests.record(turn, 1, "fixture", "wire", plan, [], "main")
    assert not await observations(runtime)
