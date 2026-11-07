"""Freeze execution facts separately from posts and actual model observations."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_coordination_admission import for_turn
from roami_agent.storage.task_request import task_user_request
from roami_agent.storage.task_result_receipts import KIND, receipt_for_run


def _source_available(db, task, origin_message_id=None):
    source = row(
        db,
        "SELECT m.* FROM messages m WHERE m.id=? AND m.conversation_id=? "
        "AND m.deleted_ms IS NULL AND m.status!='deleted' AND NOT EXISTS("
        "SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
        (
            origin_message_id or task["origin_message_id"],
            task["origin_conversation_id"],
            task["owner_id"],
        ),
    )
    return source is not None and task_user_request(db, source) is not None


def pending(db, delegation, *, limit):
    candidates = rows(
        db,
        "SELECT m.id AS member_id,t.*,a.id AS run_id,a.result_json "
        "FROM swarm_members m JOIN swarm_work_items w ON w.id=m.current_work_id "
        "JOIN tasks t ON t.id=w.task_id JOIN task_attempts a ON a.task_id=t.id "
        "AND a.task_revision=t.revision "
        "WHERE m.swarm_id=? AND t.origin_conversation_id=? "
        "AND m.id IN (SELECT value FROM json_each(?)) "
        "AND a.id=(SELECT id FROM task_attempts WHERE task_id=t.id "
        "AND task_revision=t.revision ORDER BY attempt_no DESC LIMIT 1) "
        "AND a.result_json IS NOT NULL ORDER BY t.id",
        (delegation["swarm_id"], delegation["mainConversationId"], delegation["member_ids_json"]),
    )
    result = []
    for task in candidates:
        if len(result) >= limit:
            break
        if not _source_available(db, task):
            continue
        receipt = receipt_for_run(db, task["id"], task["run_id"])
        if not receipt or row(
            db,
            "SELECT 1 FROM swarm_coordination_results WHERE delegation_id=? AND receipt_id=? "
            "UNION ALL SELECT 1 FROM swarm_result_observations WHERE delegation_id=? AND receipt_id=? LIMIT 1",
            (delegation["id"], receipt["receiptId"], delegation["id"], receipt["receiptId"]),
        ):
            continue
        result.append(
            {
                "memberId": task["member_id"],
                "taskId": task["id"],
                "taskRevision": task["revision"],
                "runId": task["run_id"],
                "originMessageId": task["origin_message_id"],
                "executionReceipt": receipt,
                "result": json.loads(task["result_json"]),
            }
        )
    return result


def freeze(db, batch_id, delegation_id, results):
    db.executemany(
        "INSERT INTO swarm_coordination_results(batch_id,delegation_id,receipt_id,payload_json) VALUES(?,?,?,?)",
        [
            (batch_id, delegation_id, item["executionReceipt"]["receiptId"], encoded(item))
            for item in results
        ],
    )


def frozen(db, batch_id):
    result = []
    for value in rows(
        db,
        "SELECT payload_json FROM swarm_coordination_results WHERE batch_id=? ORDER BY receipt_id",
        (batch_id,),
    ):
        item = json.loads(value["payload_json"])
        receipt = item["executionReceipt"]
        actual = row(db, "SELECT * FROM events WHERE id=? AND kind=?", (receipt["receiptId"], KIND))
        if (
            not actual
            or receipt != {"receiptId": actual["id"], **json.loads(actual["payload_json"])}
            or hashlib.sha256(encoded(item["result"]).encode()).hexdigest()
            != receipt["resultSha256"]
        ):
            raise DomainError("SWARM_COORDINATION_RESULT_CONFLICT", 409)
        task = row(db, "SELECT * FROM tasks WHERE id=?", (item["taskId"],))
        if not task or not _source_available(db, task, item["originMessageId"]):
            raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
        result.append(item)
    return result


def _status_receipts(db, value, message_id, content):
    stored = row(
        db,
        "SELECT native_content(m.content_json) AS body FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
        "WHERE m.id=? AND x.turn_id=? AND x.tool_name='task_status' AND x.state='succeeded' "
        "AND m.conversation_id=? AND m.deleted_ms IS NULL AND m.status!='deleted' "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
        (message_id, value["turn_id"], value["conversation_id"], value["owner_id"]),
    )
    if not stored or json.loads(stored["body"]).get("text") != content:
        return []
    try:
        tasks = json.loads(content)
    except (ValueError, TypeError):
        return []
    if not isinstance(tasks, list):
        return []
    allowed = {
        item["task_id"]
        for item in rows(
            db,
            "SELECT w.task_id FROM swarm_members m JOIN swarm_work_items w ON w.id=m.current_work_id "
            "WHERE m.swarm_id=? AND m.id IN (SELECT value FROM json_each(?))",
            (value["swarm_id"], value["delegation"]["member_ids_json"]),
        )
    }
    result = []
    for task in tasks:
        if (
            not isinstance(task, dict)
            or task.get("id") not in allowed
            or task.get("contextExcluded")
        ):
            continue
        actual_task = row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        if not actual_task or not _source_available(db, actual_task, task.get("origin_message_id")):
            raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
        receipt = (task.get("latestAttempt") or {}).get("executionReceipt")
        if not isinstance(receipt, dict) or type(receipt.get("receiptId")) is not int:
            continue
        if (
            receipt.get("taskId") != task["id"]
            or receipt.get("taskRevision") != task.get("revision")
            or receipt.get("runId") != task["latestAttempt"].get("runId")
        ):
            continue
        actual = row(
            db,
            "SELECT * FROM events WHERE id=? AND kind=? AND task_id=? AND conversation_id=?",
            (receipt["receiptId"], KIND, task["id"], value["conversation_id"]),
        )
        if actual and receipt == {"receiptId": actual["id"], **json.loads(actual["payload_json"])}:
            result.append(receipt["receiptId"])
    return result


def status_evidence(db, turn, prompt):
    if turn.get("trigger_kind") != "continuation":
        return []
    value = for_turn(db, turn)
    if value is None:
        return []
    result = []
    for item in prompt:
        if item.get("role") != "tool" or not isinstance(item.get("content"), str):
            continue
        call = row(
            db,
            "SELECT result_message_id FROM tool_calls WHERE turn_id=? AND idempotency_key=? "
            "AND tool_name='task_status' AND state='succeeded'",
            (turn["id"], turn["id"] + ":" + str(item.get("tool_call_id"))),
        )
        if not call:
            continue
        for receipt_id in _status_receipts(db, value, call["result_message_id"], item["content"]):
            result.append(
                {
                    "receiptId": receipt_id,
                    "messageId": call["result_message_id"],
                    "sha256": hashlib.sha256(item["content"].encode()).hexdigest(),
                }
            )
    return result


def record_observations(db, turn, manifest_id, projected):
    if turn.get("trigger_kind") != "continuation":
        if projected:
            raise DomainError("SWARM_COORDINATION_CONTEXT_MISMATCH", 409)
        return
    value = for_turn(db, turn)
    if value is None:
        if projected:
            raise DomainError("SWARM_COORDINATION_CONTEXT_MISMATCH", 409)
        return
    observations = {
        item["executionReceipt"]["receiptId"]: {
            "kind": "coordination_batch",
            "batchId": value["id"],
        }
        for item in frozen(db, value["id"])
    }
    for item in projected or []:
        source = row(
            db,
            "SELECT native_content(content_json) AS body FROM messages WHERE id=?",
            (item["messageId"],),
        )
        content = json.loads(source["body"]).get("text", "") if source else ""
        if hashlib.sha256(content.encode()).hexdigest() != item["sha256"] or item[
            "receiptId"
        ] not in _status_receipts(db, value, item["messageId"], content):
            raise DomainError("SWARM_COORDINATION_CONTEXT_MISMATCH", 409)
        observations[item["receiptId"]] = {"kind": "task_status", **item}
    db.executemany(
        "INSERT INTO swarm_result_observations(delegation_id,receipt_id,manifest_id,source_json) VALUES(?,?,?,?)",
        [
            (value["delegation_id"], receipt_id, manifest_id, encoded(source))
            for receipt_id, source in observations.items()
        ],
    )
