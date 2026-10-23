"""Bounded, credential-free execution facts for the conversation timeline."""

import json
import re

from roami_agent.dispatch.routing import public_routing
from roami_agent.protocol.errors import public_error_code
from roami_agent.storage.database import rows


def task_activity_title(spec):
    initial = spec.get("initialIntent")
    initial = initial if isinstance(initial, dict) else {}
    title = initial.get("title") or spec.get("title")
    if isinstance(title, str) and title.strip():
        return " ".join(title.split())[:80]
    goal = initial.get("goal") or spec.get("goal")
    if not isinstance(goal, str):
        return None
    goal = re.sub(r"https?://\S+|/(?:[^\s，。；：]+/)*[^\s，。；：]*", "", goal)
    return " ".join(re.split(r"[\n。；：]|\.\s", goal)[0].split())[:80] or None


def conversation_activity(db, cid, transcript, *, task_id=None, main_only=False):
    visible = {m["id"] for m in transcript}
    tasks = rows(
        db,
        "SELECT * FROM tasks WHERE origin_conversation_id=? "
        + ("AND id=? " if task_id else "")
        + "ORDER BY created_ms DESC LIMIT 200",
        (cid, task_id) if task_id else (cid,),
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
            started = rows(
                db,
                "SELECT turn_id FROM events WHERE task_id=? AND kind IN ('task.started','task.preparing') "
                "AND json_extract(payload_json,'$.runId')=? ORDER BY id LIMIT 1",
                (task["id"], attempt["id"]),
            )
            if started and started[0]["turn_id"]:
                child_turns[started[0]["turn_id"]] = task
        report = json.loads(attempt["result_json"]) if attempt.get("result_json") else {}
        target = spec.get("target") or {}
        activities.append(
            {
                "id": "task:" + task["id"],
                "kind": "task",
                "name": spec["executor"],
                "title": task_activity_title(spec),
                "anchorMessageId": anchor(task),
                "taskId": task["id"],
                "parentTaskId": task["parent_task_id"],
                "state": "unknown"
                if report.get("outcomeKnown") is False or attempt.get("state") == "unknown"
                else task["state"],
                "target": attempt.get("session_id")
                or target.get("sessionId")
                or target.get("projectId")
                or target.get("name"),
                "startedMs": task["created_ms"],
                "updatedMs": task["updated_ms"],
                "errorCode": public_error_code(report.get("summary"))
                if task["state"] in {"failed", "interrupted"}
                else None,
                **(
                    {"routingDecision": public_routing(spec["routingDecision"])}
                    if spec.get("routingDecision")
                    else {}
                ),
                "external": spec["executor"] in {"codex", "claude", "opencode", "pi"},
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
    routing = {
        item["event_key"][8:]: json.loads(item["payload_json"])["decision"]
        for item in rows(
            db,
            "SELECT event_key,payload_json FROM events WHERE conversation_id=? AND kind='routing.decided' ORDER BY id DESC LIMIT 200",
            (cid,),
        )
    }
    for call in calls:
        task = child_turns.get(call["turn_id"])
        if not task and (task_id or call["assistant_message_id"] not in visible):
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
        command_failed = (
            call["tool_name"] == "shell"
            and call["state"] == "succeeded"
            and isinstance(value, dict)
            and isinstance(value.get("exitCode"), int)
            and value["exitCode"] != 0
        )
        activities.append(
            {
                "id": "tool:" + call["id"],
                "kind": "tool",
                **(
                    {"routingDecision": public_routing(routing[call["idempotency_key"]])}
                    if call["idempotency_key"] in routing
                    else {}
                ),
                "name": call["tool_name"],
                "anchorMessageId": anchor(task) if task else call["assistant_message_id"],
                "taskId": task["id"] if task else None,
                "parentTaskId": task["parent_task_id"] if task else None,
                "state": "failed"
                if command_failed
                else "delivered"
                if call["state"] == "succeeded"
                and isinstance(value, dict)
                and value.get("state") == "delivered"
                else call["state"],
                "target": value.get("sessionId")
                if isinstance(value, dict) and call["tool_name"] in {"session_send", "delegate"}
                else None,
                "startedMs": call["created_ms"],
                "updatedMs": call["updated_ms"],
                "errorCode": "COMMAND_EXIT_NONZERO"
                if command_failed
                else public_error_code(value.get("error"))
                if isinstance(value, dict) and call["state"] in {"failed", "unknown"}
                else None,
            }
        )
    failures = (
        []
        if task_id
        else rows(
            db,
            "SELECT e.*,t.created_ms AS started_ms FROM events e JOIN turns t ON t.id=e.turn_id "
            "WHERE e.conversation_id=? AND e.kind IN ('turn.failed','turn.interrupted') "
            "ORDER BY e.created_ms DESC LIMIT 100",
            (cid,),
        )
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
    if main_only:
        activities = [
            item
            for item in activities
            if item["kind"] == "turn"
            or (
                item["kind"] == "task"
                and (not item["parentTaskId"] or item["state"] in {"waiting_user", "unknown"})
            )
            or (item["kind"] == "tool" and item["state"] == "unknown")
        ]
    return sorted(activities, key=lambda a: (a["startedMs"], a["id"]))[-200:]
