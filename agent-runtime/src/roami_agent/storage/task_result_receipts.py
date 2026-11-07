"""Keep host execution identity separate from Main's later acceptance."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row

KIND = "task.execution_result_recorded"


def _stored(db, task_id, run_id):
    value = row(
        db,
        "SELECT t.origin_conversation_id,a.task_id,a.task_revision,a.id AS run_id,"
        "a.result_json FROM task_attempts a JOIN tasks t ON t.id=a.task_id "
        "WHERE a.task_id=? AND a.id=?",
        (task_id, run_id),
    )
    if not value:
        raise DomainError("TASK_RUN_NOT_FOUND", 404)
    if value["result_json"] is None:
        return None
    result = json.loads(value["result_json"])
    digest = hashlib.sha256(encoded(result).encode()).hexdigest()
    payload = {
        "source": "host_execution_result",
        "taskId": value["task_id"],
        "taskRevision": value["task_revision"],
        "runId": value["run_id"],
        "resultSha256": digest,
        "executionState": result.get("state"),
        "outcomeKnown": result.get("outcomeKnown"),
        "inputStopped": result.get("inputStopped"),
    }
    return value, payload, "execution-result:" + run_id + ":" + digest


def receipt_for_run(db, task_id, run_id, *, expected_result_json=None):
    stored = _stored(db, task_id, run_id)
    if stored is None:
        return None
    value, payload, key = stored
    prior = row(db, "SELECT * FROM events WHERE event_key=?", (key,))
    if not prior:
        return None
    if (
        expected_result_json is not None
        and hashlib.sha256(encoded(json.loads(expected_result_json)).encode()).hexdigest()
        != payload["resultSha256"]
    ):
        raise DomainError("TASK_RESULT_SUPERSEDED", 409)
    if (
        prior["kind"] != KIND
        or prior["task_id"] != task_id
        or prior["conversation_id"] != value["origin_conversation_id"]
        or json.loads(prior["payload_json"]) != payload
    ):
        raise DomainError("TASK_RESULT_RECEIPT_CONFLICT", 409)
    return {"receiptId": prior["id"], **payload}


def record_execution_result(db, task_id, run_id):
    stored = _stored(db, task_id, run_id)
    if stored is None:
        raise DomainError("TASK_RESULT_REQUIRED", 409)
    value, payload, key = stored
    if payload["executionState"] is None:
        raise DomainError("TASK_RESULT_REQUIRED", 409)
    prior = receipt_for_run(db, task_id, run_id)
    if prior:
        return prior
    receipt_id = event(
        db,
        value["origin_conversation_id"],
        KIND,
        payload,
        task_id=task_id,
        key=key,
    )
    return {"receiptId": receipt_id, **payload}
