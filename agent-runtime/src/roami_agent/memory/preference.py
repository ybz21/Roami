"""Reconcile source-identical preferences before promoting their recall scope."""

from roami_agent.memory.intake import direct_user_preference, remembered_body
from roami_agent.memory.writer import commit_memory
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import rows


def _source_versions(db, memory_id):
    return {
        ref["source_key"]: ref["source_sha256"]
        for ref in rows(db, "SELECT * FROM memory_sources WHERE memory_id=?", (memory_id,))
    }


def _body(text):
    return remembered_body(text) or text.strip()


def _supersede(db, owner, previous_id, memory_id):
    db.execute(
        "INSERT OR IGNORE INTO memory_edges(parent_id,derived_id) VALUES(?,?)",
        (previous_id, memory_id),
    )
    timestamp = now_ms()
    db.execute(
        "UPDATE memory_records SET state='superseded',valid_until_ms=?,updated_ms=? WHERE id=?",
        (timestamp, timestamp, previous_id),
    )
    db.execute("UPDATE owner_versions SET memory_epoch=memory_epoch+1 WHERE owner_id=?", (owner,))


def reconcile_promoted_preferences(db):
    """Retire legacy local copies only when their existing promotion is source-identical."""
    timestamp = now_ms()
    promotions = rows(
        db,
        "SELECT p.id AS previous_id,p.body AS previous_body,g.id,g.body,g.owner_id "
        "FROM memory_edges e JOIN memory_records p ON p.id=e.parent_id "
        "JOIN memory_records g ON g.id=e.derived_id "
        "WHERE p.state='active' AND g.state='active' AND p.owner_id=g.owner_id "
        "AND p.kind='preference' AND g.kind='preference' "
        "AND p.conversation_id IS NOT NULL AND g.conversation_id IS NULL "
        "AND p.project_id IS NULL AND g.project_id IS NULL "
        "AND p.task_id IS NULL AND g.task_id IS NULL AND p.day_key IS NULL AND g.day_key IS NULL "
        "AND g.valid_from_ms<=? AND (g.valid_until_ms IS NULL OR g.valid_until_ms>?) "
        "AND (g.expires_ms IS NULL OR g.expires_ms>?)",
        (timestamp, timestamp, timestamp),
    )
    for promotion in promotions:
        if _body(promotion["previous_body"]) != _body(promotion["body"]):
            continue
        previous_sources = _source_versions(db, promotion["previous_id"])
        if previous_sources and previous_sources == _source_versions(db, promotion["id"]):
            _supersede(db, promotion["owner_id"], promotion["previous_id"], promotion["id"])


def commit_extracted_memory(db, owner, candidate, sources, scope, expected, watermark):
    confirmed = direct_user_preference(candidate, sources)
    personal = not scope.get("task_id") and not scope.get("project_id")
    promote = confirmed and personal and candidate.proposedScope == "user_preference"
    record_scope = dict(scope, conversation_id=None) if promote else scope
    source_ids = list(
        dict.fromkeys(
            candidate.sourceIds + [sid for sid in expected if sid.startswith("artifact:")]
        )
    )
    equivalents = []
    if confirmed:
        body = _body(candidate.body)
        timestamp = now_ms()
        records = rows(
            db,
            "SELECT DISTINCT r.* FROM memory_records r JOIN memory_sources s ON s.memory_id=r.id "
            "WHERE r.owner_id=? AND r.kind='preference' AND r.state='active' "
            "AND r.project_id IS ? AND r.task_id IS ? AND r.day_key IS NULL "
            "AND (r.conversation_id IS ? OR (? AND r.conversation_id IS NULL)) "
            "AND r.valid_from_ms<=? AND (r.valid_until_ms IS NULL OR r.valid_until_ms>?) "
            "AND (r.expires_ms IS NULL OR r.expires_ms>?) "
            "AND s.source_key IN (SELECT value FROM json_each(?)) ORDER BY r.created_ms,r.id",
            (
                owner,
                scope.get("project_id"),
                scope.get("task_id"),
                scope["conversation_id"],
                personal,
                timestamp,
                timestamp,
                timestamp,
                encoded(source_ids),
            ),
        )
        for record in records:
            if _body(record["body"]) == body and _source_versions(db, record["id"]) == {
                source_id: expected[source_id] for source_id in source_ids
            }:
                equivalents.append(record)

    # A later source-scoped proposal must not recreate an already promoted copy.
    if any(record["conversation_id"] is None for record in equivalents):
        record_scope = dict(scope, conversation_id=None)
    existing = next(
        (r for r in equivalents if r["conversation_id"] == record_scope["conversation_id"]), None
    )
    record = commit_memory(
        db,
        owner,
        existing["title"] if existing else candidate.title,
        existing["body"] if existing else candidate.body,
        source_ids,
        kind=candidate.kind,
        confirmed=confirmed,
        automatic=True,
        expected_sources=expected,
        source_watermark=watermark,
        **record_scope,
    )
    if record["state"] == "active":
        if confirmed and personal and record["conversation_id"] is None:
            db.execute(
                "INSERT OR IGNORE INTO memory_edges(parent_id,derived_id) "
                "SELECT DISTINCT r.id,? FROM memory_records r JOIN memory_sources s ON s.memory_id=r.id "
                "WHERE r.owner_id=? AND r.kind='preference' AND r.conversation_id=? "
                "AND r.project_id IS NULL AND r.task_id IS NULL AND r.state='active' "
                "AND s.message_id IN (SELECT value FROM json_each(?))",
                (record["id"], owner, scope["conversation_id"], encoded(candidate.sourceIds)),
            )
        for previous in equivalents:
            if previous["id"] == record["id"]:
                continue
            _supersede(db, owner, previous["id"], record["id"])
    return record
