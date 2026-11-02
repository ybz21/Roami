"""Find tracked professional work before accepting a second session in its workspace."""

import json
from pathlib import Path

from roami_agent.storage.database import rows


def continuation_candidates(db, owner, conversation, turn_id, target):
    directory = target.get("directory")
    workspace = target.get("workspaceId")
    if target.get("kind") not in {"new_session", "project"} or not (directory or workspace):
        return []
    if directory and not Path(directory).is_absolute():
        return []
    candidates = rows(
        db,
        "SELECT t.id,t.revision,t.state,t.intent_json,t.target_json,a.state AS attempt_state,a.result_json FROM tasks t "
        "JOIN turns u ON u.id=? AND u.conversation_id=t.origin_conversation_id "
        "AND u.branch_id=t.origin_branch_id "
        "JOIN messages m ON m.id=t.origin_message_id AND m.deleted_ms IS NULL "
        "LEFT JOIN task_attempts a ON a.id=(SELECT id FROM task_attempts WHERE task_id=t.id "
        "ORDER BY task_revision DESC,attempt_no DESC LIMIT 1) "
        "WHERE t.owner_id=? AND t.origin_conversation_id=? AND t.parent_task_id IS NULL "
        "AND json_extract(t.intent_json,'$.executor') IN ('codex','claude','opencode','pi','native') "
        "AND NOT EXISTS(SELECT 1 FROM task_session_closures z WHERE z.task_id=t.id AND z.state='closed') "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=t.owner_id "
        "AND o.message_id=t.origin_message_id) ORDER BY t.created_ms DESC,t.id",
        (turn_id, owner, conversation),
    )
    matched = []
    for task in candidates:
        binding = json.loads(task["target_json"]) if task["target_json"] else {}
        workdir = binding.get("workdir")
        intent = json.loads(task["intent_json"])
        result = json.loads(task["result_json"] or "{}")
        owns_children = (
            intent["executor"] != "native"
            or binding.get("projectId")
            or (intent.get("target") or {}).get("kind") in {"project", "new_project"}
            or task["state"] in {"queued", "preparing", "running", "cancelling", "interrupted"}
            or task["attempt_state"] == "unknown"
            or result.get("outcomeKnown") is False
            or result.get("inputStopped") is False
        )
        try:
            same_directory = bool(
                directory
                and workdir
                and (
                    Path(directory).resolve() == Path(workdir).resolve()
                    or owns_children
                    and Path(directory).resolve().is_relative_to(Path(workdir).resolve())
                )
            )
        except (OSError, ValueError, RuntimeError):
            same_directory = False
        if not same_directory and not (workspace and workspace == binding.get("workspaceId")):
            continue
        matched.append(
            {
                "taskId": task["id"],
                "revision": task["revision"],
                "state": task["state"],
                "title": intent.get("title"),
                "executor": intent["executor"],
            }
        )
    return matched
