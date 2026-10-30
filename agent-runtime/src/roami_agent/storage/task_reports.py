"""Keep provider reports separate from task results and acceptance evidence."""

import json
import re
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import event, row


def retain_reported_progress(db, task, run, receipt):
    progress = receipt.get("progress")
    if progress is None:
        return
    binding = receipt.get("sessionBinding") or {}
    workspace = receipt.get("workspace") or {}
    if not workspace.get("directory"):
        previous = row(
            db, "SELECT payload_json FROM events WHERE event_key=?", ("workspace:" + run["id"],)
        )
        workspace = json.loads(previous["payload_json"]).get("workspace", {}) if previous else {}
    if (
        not isinstance(progress, dict)
        or progress.get("source") != "provider_transcript"
        or not isinstance(progress.get("summary"), str)
        or not 0 < len(progress["summary"]) <= 32000
        or progress.get("providerConversationId") != binding.get("providerConversationId")
        or not progress.get("providerConversationId")
        or receipt.get("session") != binding.get("id")
        or not isinstance(progress.get("promptId"), str)
        or not progress["promptId"]
        or not isinstance(progress.get("sourceDigest"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", progress["sourceDigest"])
        or type(progress.get("observedMs")) is not int
        or progress["observedMs"] < 0
    ):
        raise DomainError("INVALID_EXECUTOR_PROGRESS")
    try:
        root = Path(workspace["directory"]).resolve(strict=True)
        directory = Path(progress["directory"])
        if not directory.is_absolute():
            raise ValueError
        directory.resolve(strict=True).relative_to(root)
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise DomainError("INVALID_EXECUTOR_PROGRESS") from error
    retained = {
        key: progress[key]
        for key in (
            "source",
            "summary",
            "directory",
            "providerConversationId",
            "promptId",
            "sourceDigest",
            "observedMs",
        )
    }
    key = "reported-progress:" + run["id"] + ":" + progress["sourceDigest"]
    if row(db, "SELECT id FROM events WHERE event_key=?", (key,)):
        return
    event(
        db,
        task["origin_conversation_id"],
        "task.execution_progress",
        {
            "taskId": task["id"],
            "runId": run["id"],
            "revision": run["task_revision"],
            "progress": retained,
        },
        task_id=task["id"],
        key=key,
    )


def reported_progress(db, task_id, run_id):
    latest = row(
        db,
        "SELECT payload_json FROM events WHERE task_id=? AND kind='task.execution_progress' "
        "AND json_extract(payload_json,'$.runId')=? ORDER BY id DESC LIMIT 1",
        (task_id, run_id),
    )
    return json.loads(latest["payload_json"])["progress"] if latest else None
