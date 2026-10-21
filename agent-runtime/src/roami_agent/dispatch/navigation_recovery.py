"""Stop evidence can admit another read-only query without rewriting an unknown outcome."""

import json

from roami_agent.storage.database import row, rows


def stopped_navigation(db, task, run):
    if (
        not run
        or run["executor_kind"] != "native"
        or run["state"] != "unknown"
        or task["target_json"]
        or json.loads(task["intent_json"]).get("target", {}).get("resourceOnly") is not True
        or json.loads(run["result_json"] or "{}").get("summary")
        not in {"TOOL_OUTCOME_UNKNOWN", "TOOL_STOP_UNCONFIRMED"}
        or row(db, "SELECT id FROM tasks WHERE parent_task_id=? LIMIT 1", (task["id"],))
    ):
        return None
    started = rows(
        db,
        "SELECT turn_id FROM events WHERE task_id=? AND kind IN ('task.started','task.preparing') "
        "AND json_extract(payload_json,'$.runId')=?",
        (task["id"], run["id"]),
    )
    if len(started) != 1:
        return None
    turn_id = started[0]["turn_id"]
    turn = row(db, "SELECT state,branch_id FROM turns WHERE id=?", (turn_id,))
    if (
        not turn
        or turn["branch_id"] != run["native_branch_id"]
        or turn["state"] not in {"failed", "interrupted", "completed", "cancelled"}
        or row(
            db,
            "SELECT id FROM resources WHERE owner_run_id=? AND "
            "(lease_until_ms IS NOT NULL OR state!='idle') LIMIT 1",
            (run["id"],),
        )
    ):
        return None
    actions = rows(
        db,
        "SELECT a.*,r.kind FROM resource_actions a JOIN resources r ON r.id=a.resource_id "
        "WHERE a.task_id=? AND a.run_id=?",
        (task["id"], run["id"]),
    )
    if not actions or any(
        action["kind"] != "browser"
        or action["state"] not in {"succeeded", "failed", "unknown"}
        or json.loads(action["result_json"] or "{}").get("inputStopped") is not True
        or json.loads(action["action_json"]).get("verb") not in {"new", "goto"}
        or not action["idempotency_key"].startswith(turn_id + ":")
        for action in actions
    ):
        return None
    pending = rows(
        db,
        "SELECT x.*,m.content_json FROM tool_calls x JOIN messages m ON m.id=x.assistant_message_id "
        "WHERE x.turn_id=? AND x.state IN ('planned','running','unknown')",
        (turn_id,),
    )
    if not pending:
        return None
    if row(
        db,
        "SELECT id FROM tool_calls WHERE turn_id=? AND effect='write' "
        "AND tool_name NOT IN ('browser_open','browser_act') LIMIT 1",
        (turn_id,),
    ):
        return None
    for call in pending:
        arguments = json.loads(call["arguments_json"])
        if call["state"] != "unknown" or not (
            call["tool_name"] == "browser_act"
            and arguments.get("kind") == "goto"
            or call["tool_name"] == "browser_open"
            and not arguments.get("targetId")
        ):
            return None
        call_ids = {item["id"] for item in json.loads(call["content_json"]).get("tool_calls", [])}
        if not any(
            action["state"] == "unknown"
            and any(
                action["idempotency_key"].startswith(turn_id + ":" + call_id + ":")
                for call_id in call_ids
            )
            and (
                call["tool_name"] == "browser_open"
                or action["observation_id"] == arguments.get("observationId")
                and arguments.get("url") in json.loads(action["action_json"]).get("args", [])
            )
            for action in actions
        ):
            return None
    return {"actionIds": [a["id"] for a in actions], "toolCallIds": [c["id"] for c in pending]}


def recovered_navigation(db, task, run):
    recorded = row(
        db,
        "SELECT payload_json FROM events WHERE task_id=? AND event_key=?",
        (task["id"], "navigation-recovery:" + run["id"]),
    )
    evidence = stopped_navigation(db, task, run) if recorded else None
    if evidence and all(
        sorted(evidence[key]) == sorted(json.loads(recorded["payload_json"]).get(key, []))
        for key in ("actionIds", "toolCallIds")
    ):
        return evidence
    return None
