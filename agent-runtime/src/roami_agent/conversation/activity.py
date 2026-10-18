"""Bounded, credential-free execution facts for the conversation timeline."""

import json

from roami_agent.protocol.errors import public_error_code
from roami_agent.storage.database import rows


def conversation_activity(db, cid, transcript):
    visible = {m["id"] for m in transcript}
    tasks = rows(
        db,
        "SELECT * FROM tasks WHERE origin_conversation_id=? ORDER BY created_ms DESC LIMIT 200",
        (cid,),
    )
    tasks = [t for t in tasks if t["origin_message_id"] in visible]
    scope = {t["id"]: t for t in tasks}
    for _ in range(3):
        if not scope:
            break
        children = rows(
            db,
            "SELECT * FROM tasks WHERE parent_task_id IN ("
            + ",".join("?" for _ in scope)
            + ") ORDER BY created_ms DESC LIMIT 200",
            tuple(scope),
        )
        new = [t for t in children if t["id"] not in scope]
        for t in new:
            scope[t["id"]] = t
        if not new:
            break

    def anchor(task):
        while task["parent_task_id"] in scope:
            task = scope[task["parent_task_id"]]
        source = json.loads(task["intent_json"]).get("sourceAssistantMessageId")
        return source if source in visible else task["origin_message_id"]

    activities = []
    child_turns = {}
    for task in scope.values():
        spec = json.loads(task["intent_json"])
        attempts = rows(
            db,
            "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
            (task["id"],),
        )
        attempt = attempts[0] if attempts else {}
        if attempt.get("native_branch_id"):
            for turn in rows(
                db,
                "SELECT id FROM turns WHERE branch_id=? ORDER BY created_ms DESC LIMIT 200",
                (attempt["native_branch_id"],),
            ):
                if len(child_turns) < 200:
                    child_turns[turn["id"]] = task
        report = json.loads(attempt["result_json"]) if attempt.get("result_json") else {}
        target = spec.get("target") or {}
        activities.append(
            {
                "id": "task:" + task["id"],
                "kind": "task",
                "name": spec["executor"],
                "anchorMessageId": anchor(task),
                "taskId": task["id"],
                "parentTaskId": task["parent_task_id"],
                "state": task["state"],
                "target": attempt.get("session_id")
                or target.get("sessionId")
                or target.get("projectId")
                or target.get("name"),
                "startedMs": task["created_ms"],
                "updatedMs": task["updated_ms"],
                "errorCode": public_error_code(report.get("summary"))
                if task["state"] in {"failed", "interrupted"}
                else None,
                "external": spec["executor"] in {"codex", "claude"},
                "delivered": bool(attempt.get("session_id"))
                and bool(
                    rows(
                        db,
                        "SELECT id FROM events WHERE task_id=? AND kind='task.started' AND json_extract(payload_json,'$.runId')=? LIMIT 1",
                        (task["id"], attempt.get("id")),
                    )
                ),
            }
        )
    calls = rows(
        db,
        "SELECT tc.*,m.content_json AS result_json FROM tool_calls tc JOIN turns t ON t.id=tc.turn_id LEFT JOIN messages m ON m.id=tc.result_message_id WHERE t.conversation_id=? ORDER BY tc.created_ms DESC LIMIT 200",
        (cid,),
    )
    if child_turns:
        calls += rows(
            db,
            "SELECT tc.*,m.content_json AS result_json FROM tool_calls tc LEFT JOIN messages m ON m.id=tc.result_message_id WHERE tc.turn_id IN ("
            + ",".join("?" for _ in child_turns)
            + ") ORDER BY tc.created_ms DESC LIMIT 200",
            tuple(child_turns),
        )
    for call in calls:
        task = child_turns.get(call["turn_id"])
        if not task and call["assistant_message_id"] not in visible:
            continue
        value = {}
        try:
            value = (
                json.loads(json.loads(call["result_json"])["text"])
                if call.get("result_json")
                else {}
            )
        except (ValueError, TypeError, KeyError):
            pass
        activities.append(
            {
                "id": "tool:" + call["id"],
                "kind": "tool",
                "name": call["tool_name"],
                "anchorMessageId": anchor(task) if task else call["assistant_message_id"],
                "taskId": task["id"] if task else None,
                "parentTaskId": task["parent_task_id"] if task else None,
                "state": "delivered"
                if call["state"] == "succeeded"
                and isinstance(value, dict)
                and value.get("state") == "delivered"
                else call["state"],
                "target": value.get("sessionId")
                if isinstance(value, dict) and call["tool_name"] == "session_send"
                else None,
                "startedMs": call["created_ms"],
                "updatedMs": call["updated_ms"],
                "errorCode": public_error_code(value.get("error"))
                if isinstance(value, dict) and call["state"] in {"failed", "unknown"}
                else None,
            }
        )
    failures = rows(
        db,
        "SELECT e.*,t.created_ms AS started_ms FROM events e JOIN turns t ON t.id=e.turn_id "
        "WHERE e.conversation_id=? AND e.kind IN ('turn.failed','turn.interrupted') "
        "ORDER BY e.created_ms DESC LIMIT 100",
        (cid,),
    )
    seen_failures = set()
    for failure in failures:
        if failure["turn_id"] in seen_failures:
            continue
        seen_failures.add(failure["turn_id"])
        messages = [m for m in transcript if m["turn_id"] == failure["turn_id"]]
        if not messages or any(json.loads(m["content_json"]).get("taskStatus") for m in messages):
            continue
        activities.append(
            {
                "id": "turn:" + failure["turn_id"],
                "kind": "turn",
                "name": "reply",
                "anchorMessageId": messages[-1]["id"],
                "state": failure["kind"].split(".")[1],
                "startedMs": failure["started_ms"],
                "updatedMs": failure["created_ms"],
                "errorCode": public_error_code(json.loads(failure["payload_json"]).get("error")),
            }
        )
    return sorted(activities, key=lambda a: (a["startedMs"], a["id"]))[-200:]
