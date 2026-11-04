"""Exclude forgotten task provenance from model-facing status responses."""

import json
from collections import Counter

from roami_agent.storage.database import row, rows
from roami_agent.storage.task_continuation import unresolved_repeated_requests
from roami_agent.storage.task_request import task_user_request


def recent_task_context(db, turn):
    tasks = rows(
        db,
        "SELECT t.id,t.revision,t.state,t.origin_message_id,t.intent_json,m.content_json,m.conversation_id,a.state AS attempt_state,a.result_json "
        "FROM tasks t JOIN messages m ON m.id=t.origin_message_id "
        "LEFT JOIN task_attempts a ON a.id=(SELECT id FROM task_attempts WHERE task_id=t.id "
        "AND task_revision=t.revision ORDER BY attempt_no DESC LIMIT 1) "
        "WHERE t.owner_id=? AND t.origin_conversation_id=? AND t.origin_branch_id=? "
        "AND t.parent_task_id IS NULL AND t.created_ms<=? AND m.deleted_ms IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=t.owner_id "
        "AND o.message_id=t.origin_message_id) ORDER BY t.created_ms DESC,t.id LIMIT 3",
        (turn["owner_id"], turn["conversation_id"], turn["branch_id"], turn["created_ms"]),
    )
    origin = row(
        db,
        "SELECT * FROM messages WHERE turn_id=? AND role='user' ORDER BY rowid LIMIT 1",
        (turn["id"],),
    )
    matched = unresolved_repeated_requests(db, turn, origin)
    tasks = list({task["id"]: task for task in [*tasks, *matched]}.values())
    source_counts = Counter(task["origin_message_id"] for task in tasks)
    result = []
    for task in tasks:
        source = task_user_request(db, {**task, "id": task["origin_message_id"]})
        if source is None:
            continue
        intent = json.loads(task["intent_json"])
        evidence = json.loads(task["result_json"]) if task["result_json"] else {}
        result.append(
            {
                "taskId": task["id"],
                "sourceMessageId": task["origin_message_id"],
                "revision": task["revision"],
                "state": task["state"],
                "goal": json.loads(source["content_json"]).get("text", ""),
                **(
                    {
                        "title": intent.get("title")
                        or intent.get("initialIntent", intent)["goal"].strip().splitlines()[0][:80]
                    }
                    if source_counts[task["origin_message_id"]] > 1
                    else {}
                ),
                "executor": intent["executor"],
                "unresolved": task["attempt_state"] == "unknown"
                or evidence.get("outcomeKnown") is False
                or evidence.get("inputStopped") is False,
            }
        )
    return result


def model_task_projection(db, owner, tasks):
    result = []
    for task in tasks:
        source = row(
            db,
            "SELECT origin_message_id FROM tasks WHERE id=? AND owner_id=?",
            (task["id"], owner),
        )
        if not source or row(
            db,
            "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
            (owner, source["origin_message_id"]),
        ):
            result.append({"id": task["id"], "state": task["state"], "contextExcluded": True})
        else:
            task = dict(task)
            if task.get("intent_json"):
                intent = json.loads(task["intent_json"])
                if intent.get("target", {}).get("resourceOnly") is True:
                    continuation = intent.get("continuation", {})
                    if "summary" in continuation:
                        continuation.pop("summary")
                        continuation["previousResultAvailable"] = True
                        task["intent_json"] = json.dumps(intent, ensure_ascii=False)
            result.append(task)
    return result
