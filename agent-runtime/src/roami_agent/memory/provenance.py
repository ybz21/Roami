"""Trace forgotten memories through tool results and conservatively reconstruct older manifests."""

import json

from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import rows
from roami_agent.storage.transcript_repository import history


def seed_dependencies(db, owner, memory):
    related = {
        item["id"]
        for item in rows(
            db,
            "SELECT id FROM memory_records WHERE owner_id=? AND (id=? OR canonical_key=?)",
            (owner, memory["id"], memory["canonical_key"]),
        )
    }
    tools = rows(
        db,
        "SELECT m.id,m.content_json FROM tool_calls x JOIN messages m ON m.id=x.result_message_id JOIN conversations c ON c.id=m.conversation_id WHERE c.owner_id=? AND x.tool_name IN ('memory_get','memory_search')",
        (owner,),
    )
    for tool in tools:
        content = json.loads(tool["content_json"])
        references = set(content.get("memoryIds", []))
        try:
            value = json.loads(content.get("text", "{}"))
        except (ValueError, TypeError):
            value = {}
        hits = (
            value
            if isinstance(value, list)
            else value.get("hits", [value])
            if isinstance(value, dict)
            else []
        )
        references.update(
            hit["id"] for hit in hits if isinstance(hit, dict) and isinstance(hit.get("id"), str)
        )
        if related & references:
            db.execute(
                "INSERT OR IGNORE INTO context_omissions(owner_id,message_id,source_memory_id,reason,created_ms) VALUES(?,?,?,'forgotten_memory_tool',?)",
                (owner, tool["id"], memory["id"], now_ms()),
            )
    for ident in related:
        db.execute(
            "INSERT OR IGNORE INTO context_omissions(owner_id,message_id,source_memory_id,reason,created_ms) "
            "SELECT ?,m.id,?,'forgotten_recalled_memory',? FROM prompt_manifests p "
            "JOIN json_each(p.parts_json,'$.memoryEvidence') evidence "
            "JOIN messages m ON m.turn_id=p.turn_id JOIN conversations c ON c.id=m.conversation_id "
            "WHERE c.owner_id=? AND m.role IN ('assistant','tool') "
            "AND json_extract(evidence.value,'$.memoryId')=?",
            (owner, memory["id"], now_ms(), owner, ident),
        )
    legacy = rows(
        db,
        "SELECT p.*,t.branch_id,t.rowid AS turn_order FROM prompt_manifests p JOIN turns t ON t.id=p.turn_id JOIN conversations c ON c.id=t.conversation_id WHERE c.owner_id=? AND json_type(p.parts_json,'$.sourceMessageIds') IS NULL",
        (owner,),
    )
    for manifest in legacy:
        parts = json.loads(manifest["parts_json"])
        source_ids = []
        for message in history(db, manifest["branch_id"]):
            if message["created_ms"] > manifest["created_ms"]:
                continue
            if message["turn_id"]:
                turn_order = db.execute(
                    "SELECT rowid FROM turns WHERE id=?", (message["turn_id"],)
                ).fetchone()[0]
                if turn_order > manifest["turn_order"]:
                    continue
            source_ids.append(message["id"])
        parts.update(
            sourceMessageIds=source_ids, sourceReconstruction="conservative-branch-history-v1"
        )
        db.execute(
            "UPDATE prompt_manifests SET parts_json=? WHERE id=?", (encoded(parts), manifest["id"])
        )
