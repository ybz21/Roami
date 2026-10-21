"""Accepted task receipts owned by one coordinator turn, including after resume."""

import json

from roami_agent.storage.database import rows


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
