"""Retain native tool diagnostics without treating them as current blockers."""

import json
import re
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import event, row


def retain_tool_diagnostic(db, task, run, receipt):
    report = receipt.get("reportedToolError")
    if report is None:
        return
    binding = receipt.get("sessionBinding") or {}
    workspace = receipt.get("workspace") or {}
    if not isinstance(binding, dict) or not isinstance(workspace, dict):
        raise DomainError("INVALID_EXECUTOR_TOOL_DIAGNOSTIC")
    if not workspace.get("directory"):
        previous = row(
            db, "SELECT payload_json FROM events WHERE event_key=?", ("workspace:" + run["id"],)
        )
        workspace = json.loads(previous["payload_json"]).get("workspace", {}) if previous else {}
    if (
        not isinstance(report, dict)
        or not isinstance(binding, dict)
        or report.get("source") != "provider_transcript"
        or report.get("code") != "CLAUDE_AUTO_CLASSIFIER_UNAVAILABLE"
        or json.loads(task["intent_json"]).get("executor") != "claude"
        or report.get("providerConversationId") != binding.get("providerConversationId")
        or not report.get("providerConversationId")
        or receipt.get("session") != binding.get("id")
        or not receipt.get("session")
        or run["task_id"] != task["id"]
        or run.get("agent_conversation_id") not in (None, report.get("providerConversationId"))
        or run.get("session_id") not in (None, receipt.get("session"))
        or any(
            not isinstance(report.get(key), str) or not 0 < len(report[key]) <= 256
            for key in ("tool", "toolUseId", "promptId")
        )
        or not isinstance(report.get("sourceDigest"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", report["sourceDigest"])
        or type(report.get("observedMs")) is not int
        or report["observedMs"] <= 0
    ):
        raise DomainError("INVALID_EXECUTOR_TOOL_DIAGNOSTIC")
    try:
        root = Path(workspace["directory"]).resolve(strict=True)
        directory = Path(report["directory"])
        if not directory.is_absolute():
            raise ValueError
        directory.resolve(strict=True).relative_to(root)
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise DomainError("INVALID_EXECUTOR_TOOL_DIAGNOSTIC") from error
    retained = {
        key: report[key]
        for key in (
            "source",
            "code",
            "tool",
            "toolUseId",
            "directory",
            "providerConversationId",
            "promptId",
            "sourceDigest",
            "observedMs",
        )
    }
    payload = {
        "taskId": task["id"],
        "runId": run["id"],
        "revision": run["task_revision"],
        "diagnosticOnly": True,
        "reported": retained,
    }
    key = "native-tool-diagnostic:" + run["id"] + ":" + retained["sourceDigest"]
    previous = row(db, "SELECT payload_json FROM events WHERE event_key=?", (key,))
    if previous:
        if json.loads(previous["payload_json"]) != payload:
            raise DomainError("EXECUTOR_TOOL_DIAGNOSTIC_CONFLICT", 409)
        return
    event(
        db,
        task["origin_conversation_id"],
        "task.execution_tool_diagnostic",
        payload,
        task_id=task["id"],
        key=key,
    )


def tool_diagnostic(db, task_id, run_id, revision):
    latest = row(
        db,
        "SELECT id,payload_json FROM events WHERE task_id=? "
        "AND kind='task.execution_tool_diagnostic' AND json_extract(payload_json,'$.runId')=? "
        "AND json_extract(payload_json,'$.revision')=? "
        "ORDER BY json_extract(payload_json,'$.reported.observedMs') DESC,id DESC LIMIT 1",
        (task_id, run_id, revision),
    )
    if latest is None:
        return None
    payload = json.loads(latest["payload_json"])
    return {"eventId": latest["id"], "diagnosticOnly": True, "reported": payload["reported"]}


def retain_tool_activity(db, task, run, receipt):
    activity = receipt.get("nativeToolActivity")
    if (
        activity is None
        or receipt.get("reportedToolError") is None
        or receipt.get("result") is not None
    ):
        return
    latest = row(
        db,
        "SELECT a.id,a.result_json FROM tasks t JOIN task_attempts a ON a.task_id=t.id AND a.task_revision=t.revision "
        "WHERE t.id=? AND t.owner_id=? AND t.state IN ('preparing','running','cancelling') "
        "ORDER BY a.attempt_no DESC LIMIT 1",
        (task["id"], task["owner_id"]),
    )
    if not latest or latest["id"] != run["id"] or latest["result_json"] is not None:
        return
    diagnostic = receipt["reportedToolError"]
    if (
        not isinstance(activity, dict)
        or any(
            activity.get(key) != diagnostic[key] for key in ("providerConversationId", "promptId")
        )
        or activity.get("classifierTool") != diagnostic["tool"]
        or not isinstance(activity.get("sourceDigest"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", activity["sourceDigest"])
        or any(
            type(activity.get(key)) is not int or activity[key] < 0
            for key in ("lastToolResultMs", "pendingTools", "consecutiveClassifierErrors")
        )
        or activity["lastToolResultMs"] < diagnostic["observedMs"]
        or type(activity.get("lastSuccessfulToolResultMs", 0)) is not int
        or not 0 <= activity.get("lastSuccessfulToolResultMs", 0) <= activity["lastToolResultMs"]
    ):
        raise DomainError("INVALID_EXECUTOR_TOOL_ACTIVITY")
    fields = (
        "providerConversationId",
        "promptId",
        "sourceDigest",
        "classifierTool",
        "lastToolResultMs",
        "lastSuccessfulToolResultMs",
        "pendingTools",
        "consecutiveClassifierErrors",
    )
    observation = {key: activity[key] for key in fields if key in activity}
    key = "native-tool-activity:" + run["id"] + ":" + activity["sourceDigest"]
    payload = {
        "taskId": task["id"],
        "runId": run["id"],
        "revision": run["task_revision"],
        "observationOnly": True,
        "diagnosticDigest": diagnostic["sourceDigest"],
        "activity": observation,
    }
    previous = row(db, "SELECT payload_json FROM events WHERE event_key=?", (key,))
    if previous:
        if json.loads(previous["payload_json"]) != payload:
            raise DomainError("EXECUTOR_TOOL_ACTIVITY_CONFLICT", 409)
        return
    event(
        db,
        task["origin_conversation_id"],
        "task.execution_tool_activity",
        payload,
        task_id=task["id"],
        key=key,
    )
