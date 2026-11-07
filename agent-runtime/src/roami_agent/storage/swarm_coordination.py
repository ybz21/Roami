"""Freeze one inbox batch and its original Main turn in the same transaction."""

import json

from roami_agent.conversation.project_wakeup import assert_main_idle
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.swarm_coordination_admission import batch_context, for_turn
from roami_agent.storage.swarm_coordination_results import freeze, frozen, pending
from roami_agent.storage.swarm_delegations import current_delegation
from roami_agent.storage.swarm_repository import changed, group


def enqueue(db, owner, swarm_id, *, limit=20):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise DomainError("INVALID_SWARM_COORDINATION")
    delegation = current_delegation(db, owner, swarm_id)
    conversation = row(
        db, "SELECT * FROM conversations WHERE id=?", (delegation["mainConversationId"],)
    )
    assert_main_idle(db, conversation)
    members = json.loads(delegation["member_ids_json"])
    results = pending(db, delegation, limit=limit)
    items = rows(
        db,
        "SELECT i.id AS inboxId,p.id AS postId,p.text,r.kind,r.author_member_id AS memberId,"
        "p.task_id AS taskId,r.source_task_revision AS taskRevision,r.source_run_id AS runId "
        "FROM swarm_inbox i JOIN swarm_post_routes r ON r.post_id=i.post_id "
        "JOIN swarm_posts p ON p.id=i.post_id JOIN swarm_members m ON m.id=r.author_member_id "
        "JOIN swarm_work_items w ON w.id=m.current_work_id AND w.task_id=p.task_id "
        "JOIN tasks t ON t.id=p.task_id "
        "WHERE i.main_conversation_id=? AND r.swarm_id=? AND i.handled_post_id IS NULL "
        "AND r.author_kind='member' AND r.author_member_id IN (SELECT value FROM json_each(?)) "
        "AND r.source_task_revision=t.revision "
        "AND r.source_run_id=(SELECT a.id FROM task_attempts a WHERE a.task_id=t.id "
        "AND a.task_revision=t.revision ORDER BY a.attempt_no DESC LIMIT 1) "
        "AND NOT EXISTS(SELECT 1 FROM swarm_coordination_inputs v WHERE v.inbox_id=i.id) "
        "ORDER BY i.id LIMIT ?",
        (conversation["id"], swarm_id, encoded(members), limit - len(results)),
    )
    if not items and not results:
        return None
    batch_id, turn_id, stamp = identity(), identity(), now_ms()
    db.execute(
        "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) "
        "VALUES(?,?,?,'continuation','queued',?)",
        (turn_id, conversation["id"], conversation["active_branch_id"], stamp),
    )
    db.execute(
        "INSERT INTO swarm_coordination_batches(id,swarm_id,delegation_id,turn_id,created_ms) "
        "VALUES(?,?,?,?,?)",
        (batch_id, swarm_id, delegation["id"], turn_id, stamp),
    )
    db.executemany(
        "INSERT INTO swarm_coordination_inputs(inbox_id,batch_id,payload_json) VALUES(?,?,?)",
        [(item["inboxId"], batch_id, encoded(item)) for item in items],
    )
    freeze(db, batch_id, delegation["id"], results)
    db.execute(
        "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
        "VALUES(?,'turn.run',?,?,?,'queued',?)",
        (
            identity(),
            turn_id,
            "swarm.coordination:" + batch_id,
            encoded({"coordinationBatchId": batch_id}),
            stamp,
        ),
    )
    event(
        db,
        conversation["id"],
        "swarm.coordination.queued",
        {
            "swarmId": swarm_id,
            "batchId": batch_id,
            "inboxIds": [item["inboxId"] for item in items],
            "resultReceiptIds": [item["executionReceipt"]["receiptId"] for item in results],
        },
        turn_id=turn_id,
    )
    return {"batchId": batch_id, "turnId": turn_id}


def admitted_batch(db, owner, turn_id, *, lease_epoch=None):
    value = batch_context(db, owner, turn_id, lease_epoch=lease_epoch)
    assert_context_admitted(db, {"id": turn_id, "owner_id": owner})
    items = rows(
        db,
        "SELECT payload_json FROM swarm_coordination_inputs WHERE batch_id=? ORDER BY inbox_id",
        (value["id"],),
    )
    return {
        **value,
        "delegation": value["delegation"],
        "inputs": [json.loads(i["payload_json"]) for i in items],
        "results": frozen(db, value["id"]),
    }


def origin(db, turn):
    value = for_turn(db, turn)
    if value is None:
        return None
    assert_context_admitted(db, turn)
    delegation = value["delegation"]
    return {"id": delegation["source_message_id"], "text": delegation["source_quote"]}


def evidence(value):
    delegation = value["delegation"]
    return {
        "batchId": value["id"],
        "swarmId": value["swarm_id"],
        "delegationId": delegation["id"],
        "delegationRevision": delegation["revision"],
        "sourceMessageId": delegation["source_message_id"],
        "inboxIds": [item["inboxId"] for item in value["inputs"]],
        "resultReceiptIds": [
            item["executionReceipt"]["receiptId"] for item in value.get("results", [])
        ],
    }


def record_retrieval(db, turn, projected):
    if turn.get("trigger_kind") != "continuation" or not row(
        db,
        "SELECT name FROM sqlite_master WHERE type='table' AND name='swarm_coordination_batches'",
    ):
        return None
    if for_turn(db, turn) is None:
        return None
    value = admitted_batch(db, turn["owner_id"], turn["id"], lease_epoch=turn["lease_epoch"])
    actual = evidence(value)
    if projected != actual:
        raise DomainError("SWARM_COORDINATION_CONTEXT_MISMATCH", 409)
    stamp, total = now_ms(), 0
    for item in value["inputs"]:
        total += db.execute(
            "UPDATE swarm_inbox SET read_ms=? WHERE id=? AND read_ms IS NULL",
            (stamp, item["inboxId"]),
        ).rowcount
    if total:
        changed(db, group(db, turn["owner_id"], value["swarm_id"]), "swarm.inbox.read")
    return actual
