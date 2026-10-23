"""Project task-bound capability receipts into the existing execution record UI."""

import json

from roami_agent.protocol.errors import public_error_code
from roami_agent.storage.database import row, rows


def professional_activity(db, scope, anchor):
    if not scope:
        return []
    calls = rows(
        db,
        "SELECT s.event_key,s.task_id,s.created_ms,a.state AS attempt_state,"
        "json_extract(s.payload_json,'$.name') AS name,"
        "json_extract(r.payload_json,'$.state') AS state,"
        "json_extract(r.payload_json,'$.result.error') AS error,"
        "json_extract(r.payload_json,'$.finishedMs') AS finished_ms "
        "FROM events s LEFT JOIN events r ON r.event_key=substr(s.event_key,1,length(s.event_key)-6)||':result' "
        "JOIN task_attempts a ON a.id=json_extract(s.payload_json,'$.runId') "
        "WHERE s.kind='capability.started' AND s.task_id IN ("
        + ",".join("?" for _ in scope)
        + ") ORDER BY s.created_ms DESC LIMIT 200",
        tuple(scope),
    )
    result = []
    for call in calls:
        task = scope[call["task_id"]]
        state = call["state"] or (
            "running"
            if call["attempt_state"] == "running" and task["state"] == "running"
            else "unknown"
        )
        result.append(
            {
                "id": call["event_key"].removesuffix(":start"),
                "kind": "tool",
                "name": call["name"],
                "anchorMessageId": anchor(task),
                "taskId": task["id"],
                "parentTaskId": task["parent_task_id"],
                "state": state,
                "startedMs": call["created_ms"],
                "updatedMs": call["finished_ms"] or call["created_ms"],
                "errorCode": public_error_code(call["error"]),
            }
        )
    return result


def professional_payload(db, aid):
    start = row(db, "SELECT payload_json FROM events WHERE event_key=?", (aid + ":start",))
    result = row(db, "SELECT payload_json FROM events WHERE event_key=?", (aid + ":result",))
    return (
        json.loads(start["payload_json"])["arguments"],
        json.loads(result["payload_json"])["result"] if result else None,
    )
