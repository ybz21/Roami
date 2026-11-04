"""Declared managed deliverables require durable evidence and explicit acceptance."""

import json
import re

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.storage.database import row, rows


def validate_deliverables(items):
    if not isinstance(items, list) or len(items) > 30:
        raise DomainError("INVALID_SWARM_DELIVERABLES")
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("kind") not in {"artifact", "external_action"}
            or not isinstance(item.get("description"), str)
            or not 1 <= len(item["description"].strip()) <= 1000
            or item.get("mimeType") is not None
            and (
                not isinstance(item["mimeType"], str)
                or not re.fullmatch(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", item["mimeType"])
            )
        ):
            raise DomainError("INVALID_SWARM_DELIVERABLES")


def requirements(db, task_id):
    work = row(db, "SELECT deliverables_json FROM swarm_work_items WHERE task_id=?", (task_id,))
    return json.loads(work["deliverables_json"]) if work else []


def evidence(db, task, run):
    artifacts = rows(
        db,
        "SELECT a.id,a.name,a.mime_type AS mimeType,a.size_bytes AS sizeBytes,a.sha256 FROM artifacts a "
        "WHERE a.owner_id=? AND a.task_id=? AND (json_extract(a.metadata_json,'$.runId')=? "
        "OR EXISTS(SELECT 1 FROM messages m JOIN events e ON e.turn_id=m.turn_id "
        "WHERE m.id=a.message_id AND e.task_id=a.task_id AND e.kind IN ('task.started','task.preparing') "
        "AND json_extract(e.payload_json,'$.runId')=?)) "
        "AND COALESCE(json_extract(metadata_json,'$.source'),'')!='native_result' "
        "AND deleted_ms IS NULL AND purged_ms IS NULL ORDER BY created_ms",
        (task["owner_id"], task["id"], run["id"], run["id"]),
    )
    for item in artifacts:
        item["downloadUrl"] = "/api/agent/artifacts/" + item["id"] + "/content"
    return artifacts


async def validate_evidence(database, task, run, *, acceptance=None):
    required = await database.call(lambda db: requirements(db, task["id"]))
    if not required:
        return None
    artifacts = await database.call(lambda db: evidence(db, task, run))
    store = ArtifactStore(database)
    available = []
    try:
        for item in artifacts:
            try:
                await store.verified_path(task["owner_id"], item["id"])
            except (DomainError, OSError):
                continue
            available.append(item)
    finally:
        await store.close()
    missing = [
        item
        for item in required
        if item["kind"] == "artifact"
        and not any(
            artifact["sizeBytes"] > 0
            and (not item.get("mimeType") or artifact["mimeType"] == item["mimeType"])
            for artifact in available
        )
    ]
    external = any(item["kind"] == "external_action" for item in required)
    receipt = None
    if external and isinstance(acceptance, dict):
        receipt = next(
            (item for item in available if item["id"] == acceptance.get("artifactId")), None
        )
        target = acceptance.get("target")
        if (
            not receipt
            or receipt["sizeBytes"] <= 0
            or not isinstance(target, str)
            or not target.strip()
            or len(target) > 2048
            or acceptance.get("state") != "confirmed"
        ):
            receipt = None
    return {
        "kind": "declared_deliverables",
        "state": "missing" if missing else "awaiting_acceptance",
        "missing": missing,
        "artifactIds": [item["id"] for item in available],
        "externalAction": "confirmed" if receipt else "unconfirmed" if external else None,
        **(
            {
                "receipt": {
                    "artifactId": receipt["id"],
                    "target": acceptance["target"].strip(),
                    "state": "confirmed",
                }
            }
            if receipt
            else {}
        ),
    }
