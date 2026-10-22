"""Source-backed browser details and bounded, explicitly related history."""

from roami_agent.memory.catalog import ACTIVE, RECORD_FIELDS, RECORD_JOINS
from roami_agent.memory.evidence import read_evidence
from roami_agent.memory.intake import remembered_body
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row, rows


def browser_record(db, owner, memory_id):
    record = row(
        db,
        "SELECT "
        + RECORD_FIELDS
        + RECORD_JOINS
        + "WHERE r.owner_id=? AND r.id=? AND r.state IN ('active','candidate','conflict')",
        (owner, memory_id),
    )
    if not record:
        raise DomainError("MEMORY_NOT_FOUND", 404)
    if record["state"] == "active" and not row(
        db,
        "SELECT r.id FROM memory_records r WHERE r.owner_id=? AND r.id=? AND " + ACTIVE,
        (owner, memory_id, *([now_ms()] * 3)),
    ):
        raise DomainError("MEMORY_NOT_FOUND", 404)
    if row(
        db,
        "SELECT 1 FROM memory_sources s JOIN context_omissions o ON o.message_id=s.message_id AND o.owner_id=? WHERE s.memory_id=?",
        (owner, memory_id),
    ):
        raise DomainError("MEMORY_SOURCE_NOT_FOUND", 404)
    return record


class MemoryDetails:
    def __init__(self, database):
        self.db = database

    async def get(self, owner, memory_id):
        def read(db):
            record = browser_record(db, owner, memory_id)
            current = (
                row(
                    db,
                    "SELECT "
                    + RECORD_FIELDS
                    + RECORD_JOINS
                    + "WHERE r.owner_id=? AND r.canonical_key=? AND r.state='active' AND "
                    + ACTIVE,
                    (owner, record["canonical_key"], *([now_ms()] * 3)),
                )
                if record["state"] != "active"
                else None
            )
            version = row(
                db,
                "SELECT id FROM memory_records WHERE owner_id=? AND canonical_key=? AND state='active'",
                (owner, record["canonical_key"]),
            )
            evidence = read_evidence(db, owner, record)
            return {
                "record": record,
                "current": current,
                "currentVersionId": version["id"] if version else "",
                "evidence": evidence,
                "canConfirm": record["state"] in {"candidate", "conflict"}
                and bool(evidence)
                and all(item.get("available") and item.get("unchanged") for item in evidence),
            }

        return await self.db.call(read)

    async def history(self, owner, memory_id):
        def read(db):
            record = browser_record(db, owner, memory_id)
            revisions = rows(
                db,
                "SELECT "
                + RECORD_FIELDS
                + RECORD_JOINS
                + "WHERE r.owner_id=? AND r.canonical_key=? AND r.state='superseded' AND NOT EXISTS (SELECT 1 FROM memory_sources s JOIN context_omissions o ON o.message_id=s.message_id AND o.owner_id=r.owner_id WHERE s.memory_id=r.id) ORDER BY r.updated_ms DESC,r.id LIMIT 51",
                (owner, record["canonical_key"]),
            )
            for item in revisions:
                item["relation"] = "revision"
            parents = rows(
                db,
                "SELECT p.*,g.body AS derived_body,g.id AS derived_id FROM memory_edges e "
                "JOIN memory_records p ON p.id=e.parent_id JOIN memory_records g ON g.id=e.derived_id "
                "WHERE p.owner_id=? AND g.owner_id=p.owner_id AND p.state='superseded' "
                "AND g.state IN ('active','superseded') AND (g.id=? OR g.canonical_key=?) "
                "AND p.kind='preference' AND g.kind='preference' "
                "AND p.conversation_id IS NOT NULL AND g.conversation_id IS NULL "
                "AND p.project_id IS NULL AND g.project_id IS NULL AND p.task_id IS NULL "
                "AND g.task_id IS NULL AND p.day_key IS NULL AND g.day_key IS NULL "
                "ORDER BY p.updated_ms DESC,p.id",
                (owner, memory_id, record["canonical_key"]),
            )
            for previous in parents:
                body = remembered_body(previous["body"]) or previous["body"].strip()
                derived = (
                    remembered_body(previous["derived_body"]) or previous["derived_body"].strip()
                )
                if body != derived:
                    continue
                refs = lambda ident: {
                    s["source_key"]: s["source_sha256"]
                    for s in rows(
                        db,
                        "SELECT source_key,source_sha256 FROM memory_sources WHERE memory_id=?",
                        (ident,),
                    )
                }
                original = refs(previous["id"])
                if original and original == refs(previous["derived_id"]):
                    previous.pop("derived_body")
                    previous.pop("derived_id")
                    previous["relation"] = "merged"
                    revisions.append(previous)
            visible = {}
            for item in revisions:
                if not row(
                    db,
                    "SELECT 1 FROM memory_sources s JOIN context_omissions o ON o.message_id=s.message_id AND o.owner_id=? WHERE s.memory_id=?",
                    (owner, item["id"]),
                ):
                    visible[item["id"]] = item
            items = sorted(
                visible.values(), key=lambda item: (item["updated_ms"], item["id"]), reverse=True
            )
            return {"items": items[:50], "truncated": len(items) > 50}

        return await self.db.call(read)
