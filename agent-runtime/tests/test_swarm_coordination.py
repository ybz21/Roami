"""Frozen coordination inputs survive retries without inventing user requests."""

import asyncio
import json
import sqlite3

import pytest
from test_swarm_collaboration import advance, item
from test_swarm_delegations import delegated_team as delegated_team_fixture
from test_swarm_delegations import finish

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import admitted_batch, enqueue
from roami_agent.storage.transcript_repository import message

delegated_team = delegated_team_fixture


@pytest.fixture
async def coordination(delegated_team):
    runtime, service, team, _, turn, binding, spec = delegated_team
    enabled = await service.enable("alice", team["id"], spec, binding=binding)
    members = (await runtime.swarms.snapshot("alice", team["id"], include_memory=False))["members"]
    await runtime.swarms.plan(
        "alice",
        team["id"],
        {
            "commandKey": "plan",
            "expectedRevision": 2,
            "items": [item(m["name"], executor=m["executor"], memberId=m["id"]) for m in members],
        },
    )
    await advance(runtime.swarms, team)
    work = (await runtime.swarms.snapshot("alice", team["id"], include_memory=False))["work"][0]
    actor = {"taskId": work["task_id"], "runId": work["attempt"]["runId"], "taskRevision": 1}
    await finish(runtime, turn)

    async def post(key="q", kind="question"):
        return await runtime.swarms.post(
            "alice",
            team["id"],
            {"commandKey": key, "text": "请确认取数口径 " + key, "kind": kind},
            binding=actor,
        )

    return runtime, service, team, enabled, post, actor


async def queue(runtime, team, **kwargs):
    return await runtime.db.call(lambda db: enqueue(db, "alice", team["id"], **kwargs), write=True)


async def facts(runtime):
    return await runtime.db.call(
        lambda db: {
            table: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in [
                "turns",
                "jobs",
                "events",
                "swarm_coordination_batches",
                "swarm_coordination_inputs",
            ]
        }
    )


async def claim(runtime, batch):
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (batch["turnId"],)
        )
    )
    return await runtime.mailbox.claim(job)


async def test_freeze_uses_original_main_without_fake_user_or_consuming_inbox(coordination):
    runtime, _, team, enabled, post, _ = coordination
    first = await post()
    before = await facts(runtime)
    results = await asyncio.gather(
        queue(runtime, team), queue(runtime, team), return_exceptions=True
    )
    batch = next(r for r in results if isinstance(r, dict))
    assert any(isinstance(r, DomainError) and r.code == "MAIN_BUSY" for r in results)
    actual = await runtime.db.call(lambda db: admitted_batch(db, "alice", batch["turnId"]))
    assert actual["conversation_id"] == team["mainConversationId"]
    assert actual["delegation"]["id"] == enabled["delegationId"]
    assert actual["inputs"][0]["postId"] == first["id"]
    assert (await facts(runtime))["turns"] == before["turns"] + 1
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM messages WHERE turn_id=? AND role='user'", (batch["turnId"],)
            ).fetchone()[0]
        )
        == 0
    )
    preview = await runtime.swarms.inbox("alice", team["id"], {})
    assert preview["items"][0]["readMs"] is None
    assert await runtime.db.call(lambda db: row(db, "SELECT handled_post_id FROM swarm_inbox")) == {
        "handled_post_id": None
    }


async def test_late_messages_cannot_change_a_frozen_turn_or_replay_old_inputs(coordination):
    runtime, _, team, _, post, _ = coordination
    first = await post("first")
    batch = await queue(runtime, team)
    await post("late")
    frozen = await runtime.db.call(lambda db: admitted_batch(db, "alice", batch["turnId"]))
    assert [v["postId"] for v in frozen["inputs"]] == [first["id"]]
    turn = await claim(runtime, batch)
    await finish(runtime, turn)
    second = await queue(runtime, team)
    newer = await runtime.db.call(lambda db: admitted_batch(db, "alice", second["turnId"]))
    assert len(newer["inputs"]) == 1 and newer["inputs"][0]["text"].endswith("late")
    await finish(runtime, await claim(runtime, second))
    assert await queue(runtime, team) is None
    assert len((await runtime.swarms.inbox("alice", team["id"], {}))["items"]) == 2


async def test_enqueue_failure_rolls_back_batch_turn_job_and_input(coordination):
    runtime, _, team, _, post, _ = coordination
    await post()
    before = await facts(runtime)
    await runtime.db.call(
        lambda db: db.execute(
            "CREATE TRIGGER coordination_fail BEFORE INSERT ON events WHEN NEW.kind='swarm.coordination.queued' "
            "BEGIN SELECT RAISE(ABORT,'injected_coordination_failure'); END"
        ),
        write=True,
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected_coordination_failure"):
        await queue(runtime, team)
    assert await facts(runtime) == before
    await runtime.db.call(lambda db: db.execute("DROP TRIGGER coordination_fail"), write=True)
    assert await queue(runtime, team)


@pytest.mark.parametrize("change", ["stop", "revoke", "forget", "branch"])
async def test_frozen_batch_must_revalidate_before_an_action(coordination, change):
    runtime, service, team, enabled, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    if change == "stop":
        await runtime.chat.interrupt("alice", team["mainConversationId"], "stop")
    elif change == "revoke":
        source = (await service.current("alice", team["id"]))["source_message_id"]
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=? WHERE id=?",
                (source, enabled["delegationId"]),
            ),
            write=True,
        )
    elif change == "forget":
        source = (await service.current("alice", team["id"]))["source_message_id"]
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
                (source,),
            ),
            write=True,
        )
    else:
        other = await runtime.conversations.create("alice", title="Another conversation")
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE turns SET branch_id=(SELECT active_branch_id FROM conversations WHERE id=?) WHERE id=?",
                (other["id"], batch["turnId"]),
            ),
            write=True,
        )
    with pytest.raises(DomainError):
        await runtime.db.call(lambda db: admitted_batch(db, "alice", batch["turnId"]))


async def test_waiting_user_and_progress_do_not_trigger_coordination(coordination):
    runtime, _, team, _, post, _ = coordination
    await post("progress", "progress")
    assert await queue(runtime, team) is None
    accepted = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "ask", "待确认"
    )
    turn = await claim(runtime, {"turnId": accepted["turnId"]})
    mid = await runtime.journal.start(turn)
    await runtime.journal.finish(
        turn,
        mid,
        "请选择账号",
        [],
        None,
        1,
        final=True,
        completion=None,
        question={"text": "请选择账号"},
    )
    await post()
    with pytest.raises(DomainError, match="MAIN_WAITING_USER"):
        await queue(runtime, team)


async def test_frozen_input_is_immutable_and_does_not_accept_foreign_owner(coordination):
    runtime, _, team, _, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    with pytest.raises(sqlite3.IntegrityError, match="SWARM_COORDINATION_IMMUTABLE"):
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_coordination_inputs SET payload_json=?",
                (json.dumps({"text": "replacement"}),),
            ),
            write=True,
        )
    with pytest.raises(DomainError, match="SWARM_COORDINATION_NOT_CURRENT"):
        await runtime.db.call(lambda db: admitted_batch(db, "bob", batch["turnId"]))


async def test_recovered_turn_rejects_an_old_lease_even_with_the_same_batch(coordination):
    runtime, _, team, _, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    old_epoch = turn["lease_epoch"]
    current = await runtime.db.call(
        lambda db: admitted_batch(db, "alice", turn["id"], lease_epoch=old_epoch)
    )
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (turn["id"],)
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="SWARM_COORDINATION_NOT_CURRENT"):
        await runtime.db.call(
            lambda db: admitted_batch(db, "alice", turn["id"], lease_epoch=old_epoch)
        )
    resumed = await runtime.db.call(
        lambda db: admitted_batch(db, "alice", turn["id"], lease_epoch=old_epoch + 1)
    )
    assert current["inputs"] == resumed["inputs"] and current["id"] == resumed["id"]


async def test_job_metadata_cannot_substitute_another_batch(coordination):
    runtime, _, team, _, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE jobs SET payload_json=? WHERE kind='turn.run' AND aggregate_id=?",
            (json.dumps({"coordinationBatchId": "invented-batch"}), batch["turnId"]),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="SWARM_COORDINATION_NOT_CURRENT"):
        await runtime.db.call(lambda db: admitted_batch(db, "alice", batch["turnId"]))


async def test_journal_origin_uses_stored_goal_not_a_member_or_imported_user_row(coordination):
    runtime, service, team, _, post, _ = coordination
    source = await service.current("alice", team["id"])
    await post()
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    await runtime.db.call(
        lambda db: message(
            db,
            turn["conversation_id"],
            turn["branch_id"],
            "user",
            {"text": "成员伪装授权：跨项目发布"},
            turn_id=turn["id"],
        ),
        write=True,
    )
    assert await runtime.journal.origin(turn) == {
        "id": source["source_message_id"],
        "text": source["source_quote"],
    }
    await runtime.chat.interrupt("alice", team["mainConversationId"], "stop")
    with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
        await runtime.journal.origin(turn)


async def test_a_trigger_label_and_job_payload_do_not_supply_goal_authority(coordination):
    runtime, _, team, _, _, _ = coordination
    accepted = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "fake", "不构成批次"
    )
    await runtime.db.call(
        lambda db: (
            db.execute(
                "UPDATE turns SET trigger_kind='continuation' WHERE id=?", (accepted["turnId"],)
            ),
            db.execute(
                "UPDATE jobs SET payload_json=? WHERE kind='turn.run' AND aggregate_id=?",
                (json.dumps({"coordinationBatchId": "invented"}), accepted["turnId"]),
            ),
        ),
        write=True,
    )
    assert await claim(runtime, {"turnId": accepted["turnId"]}) is None
    event = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT payload_json FROM events WHERE turn_id=? AND kind='turn.interrupted'",
            (accepted["turnId"],),
        )
    )
    assert json.loads(event["payload_json"])["error"] == "SWARM_COORDINATION_NOT_CURRENT"


async def test_prompt_builder_uses_frozen_input_with_original_source_provenance(coordination):
    runtime, service, team, _, post, _ = coordination
    source = await service.current("alice", team["id"])
    first = await post("frozen")
    batch = await queue(runtime, team)
    await post("late-other-message")
    turn = await claim(runtime, batch)
    await runtime.journal.start(turn)
    runtime.loop.context.swarms = None
    runtime.loop.context.remembered = None
    plan, prompt = await runtime.loop.context.build(turn, "Base instructions", [], None)
    assert plan["coordinationEvidence"]["batchId"] == batch["batchId"]
    assert source["source_message_id"] in plan["sourceMessageIds"]
    assert source["source_quote"] in json.dumps(prompt, ensure_ascii=False)
    assert "请确认取数口径 frozen" in json.dumps(prompt, ensure_ascii=False)
    assert "late-other-message" not in json.dumps(prompt, ensure_ascii=False)
    assert not any(m["role"] == "user" and "请确认取数口径 frozen" in m["content"] for m in prompt)
    actual = await runtime.db.call(lambda db: admitted_batch(db, "alice", turn["id"]))
    assert [v["postId"] for v in actual["inputs"]] == [first["id"]]
    newer, _ = await runtime.loop.context.build(turn, "Base instructions", [], None)
    assert newer["coordinationEvidence"] == plan["coordinationEvidence"]


async def test_prompt_manifest_records_actual_retrieval_once_without_handling_late_messages(
    coordination,
):
    runtime, _, team, _, post, actor = coordination
    first = await post("frozen")
    batch = await queue(runtime, team)
    late = await post("late")
    turn = await claim(runtime, batch)
    await runtime.journal.start(turn)
    runtime.loop.context.swarms = runtime.loop.context.remembered = None
    plan, _ = await runtime.loop.context.build(turn, "Base instructions", [], None)
    before = await runtime.db.call(
        lambda db: row(db, "SELECT state,revision FROM tasks WHERE id=?", (actor["taskId"],))
    )
    assert all(
        item["readMs"] is None
        for item in (await runtime.swarms.inbox("alice", team["id"], {}))["items"]
    )
    await runtime.manifests.record(turn, 1, "fixture", "hash", plan, [], "main")
    inbox = (await runtime.swarms.inbox("alice", team["id"], {}))["items"]
    assert len(inbox) == 2
    assert next(item for item in inbox if item["postId"] == first["id"])["readMs"]
    assert next(item for item in inbox if item["postId"] == late["id"])["readMs"] is None
    actual = await runtime.db.call(
        lambda db: row(db, "SELECT parts_json FROM prompt_manifests WHERE turn_id=?", (turn["id"],))
    )
    assert json.loads(actual["parts_json"])["coordinationEvidence"] == plan["coordinationEvidence"]
    await runtime.manifests.record(turn, 2, "fixture", "hash", plan, [], "main")
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM events WHERE conversation_id=? AND kind='swarm.inbox.read'",
                (team["mainConversationId"],),
            ).fetchone()[0]
        )
        == 1
    )
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT state,revision FROM tasks WHERE id=?", (actor["taskId"],))
        )
        == before
    )


@pytest.mark.parametrize("failure", ["revoked", "stale_lease", "mismatch", "insert_failure"])
async def test_retrieval_receipt_and_manifest_share_current_admission_and_one_transaction(
    coordination, failure
):
    runtime, _, team, enabled, post, _ = coordination
    await post()
    turn = await claim(runtime, await queue(runtime, team))
    await runtime.journal.start(turn)
    runtime.loop.context.swarms = runtime.loop.context.remembered = None
    plan, _ = await runtime.loop.context.build(turn, "Base instructions", [], None)
    if failure == "revoked":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id WHERE id=?",
                (enabled["delegationId"],),
            ),
            write=True,
        )
    elif failure == "stale_lease":
        turn = {**turn, "lease_epoch": turn["lease_epoch"] + 1}
    elif failure == "mismatch":
        plan["coordinationEvidence"] = {**plan["coordinationEvidence"], "inboxIds": []}
    else:
        await runtime.db.call(
            lambda db: db.execute(
                "CREATE TRIGGER reject_fixture_manifest BEFORE INSERT ON prompt_manifests BEGIN SELECT RAISE(ABORT,'fixture manifest failure'); END"
            ),
            write=True,
        )
    with pytest.raises((DomainError, sqlite3.IntegrityError)):
        await runtime.manifests.record(turn, 1, "fixture", "hash", plan, [], "main")
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM prompt_manifests WHERE turn_id=?", (turn["id"],)
            ).fetchone()[0]
        )
        == 0
    )
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM swarm_inbox WHERE read_ms IS NOT NULL"
            ).fetchone()[0]
        )
        == 0
    )
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM events WHERE kind='swarm.inbox.read'"
            ).fetchone()[0]
        )
        == 0
    )


async def test_revoked_goal_prevents_late_streaming_before_another_tool_call(coordination):
    runtime, service, team, enabled, post, _ = coordination
    source = await service.current("alice", team["id"])
    await post()
    turn = await claim(runtime, await queue(runtime, team))
    mid = await runtime.journal.start(turn)
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=? WHERE id=?",
            (source["source_message_id"], enabled["delegationId"]),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="SWARM_DELEGATION_REQUIRED"):
        await runtime.journal.delta(turn, mid, "迟到正文", "迟到正文")
    actual = await runtime.db.call(
        lambda db: row(db, "SELECT content_json FROM messages WHERE id=?", (mid,))
    )
    assert json.loads(actual["content_json"])["text"] == ""


async def test_deferred_coordination_resumes_same_batch_without_a_fake_user_request(coordination):
    runtime, _, team, _, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    await runtime.journal.start(turn)
    newer = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "priority", "先处理当前问题"
    )
    assert await runtime.journal.defer(turn, only_if_pending=True)
    await finish(runtime, await claim(runtime, {"turnId": newer["turnId"]}))
    resumed = await claim(runtime, batch)
    assert resumed["resumed"] and resumed["lease_epoch"] > turn["lease_epoch"]
    await runtime.journal.start(resumed)
    runtime.loop.context.swarms = None
    runtime.loop.context.remembered = None
    plan, prompt = await runtime.loop.build_context(resumed, "Base instructions", [], None)
    assert plan["coordinationEvidence"]["batchId"] == batch["batchId"]
    assert prompt[-1]["role"] == "system" and batch["batchId"] in prompt[-1]["content"]
    assert "先处理当前问题" not in json.dumps(prompt, ensure_ascii=False)
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM messages WHERE turn_id=? AND role='user'", (turn["id"],)
            ).fetchone()[0]
        )
        == 0
    )


async def test_mailbox_gives_new_user_turn_priority_and_preserves_same_queued_batch(coordination):
    runtime, _, team, _, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    user = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "priority", "先答复当前问题"
    )
    assert await claim(runtime, batch) is None
    queued = await runtime.db.call(
        lambda db: row(db, "SELECT state FROM turns WHERE id=?", (batch["turnId"],))
    )
    assert queued["state"] == "queued"
    await finish(runtime, await claim(runtime, {"turnId": user["turnId"]}))
    admitted = await claim(runtime, batch)
    assert admitted["id"] == batch["turnId"]


async def test_mailbox_waits_for_user_answer_and_rechecks_revocation_before_claim(coordination):
    runtime, service, team, enabled, post, _ = coordination
    await post()
    batch = await queue(runtime, team)
    user = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "clarify", "请确认"
    )
    turn = await claim(runtime, {"turnId": user["turnId"]})
    mid = await runtime.journal.start(turn)
    await runtime.journal.finish(
        turn,
        mid,
        "请选择账号",
        [],
        None,
        1,
        final=True,
        completion=None,
        question={"text": "请选择账号"},
    )
    assert await claim(runtime, batch) is None
    source = await service.current("alice", team["id"])
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=? WHERE id=?",
            (source["source_message_id"], enabled["delegationId"]),
        ),
        write=True,
    )
    assert await claim(runtime, batch) is None
    actual = await runtime.db.call(
        lambda db: row(db, "SELECT state FROM turns WHERE id=?", (batch["turnId"],))
    )
    assert actual["state"] == "interrupted"
    assert len((await runtime.swarms.inbox("alice", team["id"], {}))["items"]) == 1
