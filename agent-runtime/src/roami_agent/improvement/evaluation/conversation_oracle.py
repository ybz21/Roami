"""Judge persisted conversation decisions without giving the Actor reference answers."""

import json
import re


def prose(value):
    return re.sub(r"[\s:：\"'“”‘’「」『』（）()]", "", value or "").casefold()


def same_json(actual, expected):
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return (type(actual) is bool) == (type(expected) is bool) and actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            same_json(actual[k], value) for k, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            same_json(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return actual == expected


def grade_checkpoint(expect, snapshot, bindings):
    failures = []
    tasks = snapshot["tasks"]
    if len(tasks) != expect["task_count"]:
        failures.append("TASK_COUNT_MISMATCH")
    for spec in expect.get("tasks", []):
        alias = spec["alias"]
        task_id = bindings.get(alias)
        if task_id:
            matches = [task for task in tasks if task["id"] == task_id]
        else:
            candidates = [task for task in tasks if task["id"] not in bindings.values()]
            if "created_turn" in spec:
                candidates = [
                    task for task in candidates if task.get("created_turn") == spec["created_turn"]
                ]
            peers = [
                item
                for item in expect.get("tasks", [])
                if item.get("created_turn") == spec.get("created_turn")
            ]
            if "created_turn" in spec and len(candidates) == len(peers) == 1:
                matches = candidates
            else:
                matches = [
                    task
                    for task in candidates
                    if prose(spec["match"]) in prose(task.get("title", ""))
                ]
                if not matches:
                    matches = [
                        task for task in candidates if prose(spec["match"]) in prose(task["goal"])
                    ]
        if len(matches) != 1:
            failures.append("TASK_IDENTITY_MISMATCH:" + alias)
            continue
        task = matches[0]
        if task_id is None and task["id"] in bindings.values():
            failures.append("INDEPENDENT_TASKS_MERGED:" + alias)
            continue
        bindings[alias] = task["id"]
        if task["revision"] != spec["revision"]:
            failures.append("TASK_REVISION_MISMATCH:" + alias)
        if any(prose(part) not in prose(task["goal"]) for part in spec.get("contains", [])):
            failures.append("TASK_REQUIREMENTS_MISSING:" + alias)
        if any(
            part not in task.get("user_contract", "") for part in spec.get("source_contains", [])
        ):
            failures.append("TASK_SOURCE_REQUIREMENTS_MISSING:" + alias)
        if any(part in task["goal"] for part in spec.get("excludes", [])):
            failures.append("TASK_REQUIREMENTS_MIXED:" + alias)
        if spec.get("executor") and task["executor"] != spec["executor"]:
            failures.append("TASK_EXECUTOR_MISMATCH:" + alias)
        if "attachments" in spec and sorted(task["attachments"]) != sorted(spec["attachments"]):
            failures.append("TASK_INPUTS_MISMATCH:" + alias)
        if task["conversation_id"] != snapshot["conversation_id"]:
            failures.append("TASK_CONVERSATION_MISMATCH:" + alias)
        if task["current_run_count"] != 1 or task["attempt_count"] != task["revision"]:
            failures.append("TASK_ATTEMPTS_MISMATCH:" + alias)
        if "project_id" in spec and task["project_id"] != spec["project_id"]:
            failures.append("TASK_TARGET_MISMATCH:" + alias)
    if "reply_json" in expect:
        try:
            answer = json.loads(snapshot["answer"])
        except ValueError:
            failures.append("CHAT_JSON_REQUIRED")
        else:
            if not same_json(answer, expect["reply_json"]):
                failures.append("CHAT_CONSTRAINTS_MISMATCH")
    if any(text not in snapshot["answer"] for text in expect.get("reply_contains", [])):
        failures.append("CHAT_CONTENT_MISSING")
    if any(text in snapshot["answer"] for text in expect.get("reply_excludes", [])):
        failures.append("CHAT_CONTENT_UNEXPECTED")
    forbidden = set(expect.get("forbidden_tools", []))
    if forbidden.intersection(snapshot["tools"]):
        failures.append("UNEXPECTED_TOOL_EFFECT")
    if expect.get("question") and not snapshot["question"]:
        failures.append("CLARIFICATION_REQUIRED")
    if snapshot["turn_state"] != "completed":
        failures.append("TURN_NOT_COMPLETED")
    if snapshot["pending_steers"]:
        failures.append("CONTINUATION_NOT_APPLIED")
    return {"passed": not failures, "failures": failures}
