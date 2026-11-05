"""Confirmed provider bindings survive attempts that provably accepted no input."""

import json

from roami_agent.storage.database import row, rows


def provider_binding(db, task, source_id, through_attempt):
    source = row(
        db,
        "SELECT a.* FROM task_attempts a JOIN tasks t ON t.id=a.task_id "
        "WHERE a.id=? AND a.task_id=? AND t.owner_id=? AND a.attempt_no<=? "
        "AND a.executor_kind='cli'",
        (source_id, task["id"], task["owner_id"], through_attempt),
    )
    if (
        not source
        or not source["session_id"]
        or not source["agent_conversation_id"]
        or source["node_id"] not in {None, "local"}
        or source["state"] == "unknown"
    ):
        return None
    result = json.loads(source["result_json"]) if source["result_json"] else {}
    if result.get("outcomeKnown") is not True or result.get("inputStopped") is not True:
        return None
    for attempt in rows(
        db,
        "SELECT state,result_json,agent_conversation_id FROM task_attempts "
        "WHERE task_id=? AND attempt_no>? AND attempt_no<=?",
        (task["id"], source["attempt_no"], through_attempt),
    ):
        result = json.loads(attempt["result_json"]) if attempt["result_json"] else {}
        if (
            attempt["state"] == "unknown"
            or attempt["agent_conversation_id"]
            or result.get("executionStarted") is not False
            or result.get("outcomeKnown") is not True
            or result.get("inputStopped") is not True
        ):
            return None
    return source
