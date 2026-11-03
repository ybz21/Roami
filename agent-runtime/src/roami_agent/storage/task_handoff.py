"""Accepted task receipts owned by one coordinator turn, including after resume."""

import json

from roami_agent.storage.database import row, rows
from roami_agent.storage.task_request import task_user_request


def request_handoff_complete(db, message_id):
    source = row(db, "SELECT * FROM messages WHERE id=?", (message_id,))
    source = task_user_request(db, source) if source else None
    return bool(
        source
        and source["turn_id"]
        and any(
            receipt.get("requestComplete") is True
            for receipt in accepted_handoffs(db, source["turn_id"]).values()
        )
    )


def accepted_handoffs(db, turn_id):
    receipts = {}
    for result in rows(
        db,
        "SELECT m.content_json FROM tool_calls c JOIN messages m ON m.id=c.result_message_id "
        "WHERE c.turn_id=? AND c.tool_name IN ('delegate','task_steer') AND c.state='succeeded' "
        "ORDER BY c.rowid",
        (turn_id,),
    ):
        value = json.loads(json.loads(result["content_json"])["text"])
        if isinstance(value, dict) and value.get("acceptedOnly") is True and value.get("taskId"):
            receipts[value["taskId"]] = value
    return receipts


def handoff_receipt_context(db, message_ids):
    if not message_ids:
        return {}
    receipts = {}
    for result in rows(
        db,
        "WITH visible AS (SELECT value AS id FROM json_each(?)) "
        "SELECT m.id,m.content_json,c.tool_name FROM tool_calls c "
        "JOIN messages m ON m.id=c.result_message_id WHERE m.id IN (SELECT id FROM visible) "
        "AND c.tool_name IN ('delegate','task_steer') AND c.state='succeeded' "
        "AND EXISTS(SELECT 1 FROM messages u WHERE u.turn_id=c.turn_id AND u.role='user' "
        "AND u.id IN (SELECT id FROM visible))",
        (json.dumps(message_ids),),
    ):
        value = json.loads(json.loads(result["content_json"])["text"])
        if (
            not isinstance(value, dict)
            or value.get("acceptedOnly") is not True
            or not isinstance(value.get("taskId"), str)
            or not value["taskId"]
        ):
            continue
        receipt = {
            "operation": result["tool_name"],
            "taskId": value["taskId"],
            "acceptedOnly": True,
        }
        if type(value.get("requestComplete")) is bool:
            receipt["requestComplete"] = value["requestComplete"]
        if type(value.get("revision")) is int and value["revision"] > 0:
            receipt["revision"] = value["revision"]
        receipts[result["id"]] = receipt
    return receipts
