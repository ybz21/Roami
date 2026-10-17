"""Recomputable local-day activity memories from immutable events and unique identities."""

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.retrieval.tokens import search_tokens
from roami_agent.storage.database import row, rows

DAILY_KINDS = (
    "message.accepted",
    "task.intent",
    "task.accepted",
    "task.succeeded",
    "task.failed",
    "task.cancelled",
    "task.interrupted",
)


def day_bounds(day_key, timezone_name):
    try:
        day = date.fromisoformat(day_key)
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise DomainError("INVALID_MEMORY_DAY") from exc
    start = datetime.combine(day, time.min, zone)
    end = datetime.combine(day + timedelta(days=1), time.min, zone)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def event_day(timestamp, timezone_name):
    try:
        return (
            datetime.fromtimestamp(timestamp / 1000, UTC)
            .astimezone(ZoneInfo(timezone_name))
            .date()
            .isoformat()
        )
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise DomainError("INVALID_MEMORY_DAY") from exc


class DailyMemories:
    def __init__(self, database, timezone_name="UTC"):
        self.db, self.timezone = database, timezone_name
        day_bounds("2024-01-01", timezone_name)

    async def refresh(self, owner, day_key=None, timezone_name=None):
        zone = timezone_name or self.timezone
        day_key = day_key or event_day(now_ms(), zone)
        start, end = day_bounds(day_key, zone)
        watermark = await self.db.call(
            lambda db: db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
        )
        groups, cursor = {}, 0
        while True:

            def page(db, cursor=cursor):
                events = rows(
                    db,
                    "SELECT e.*,t.intent_json,(SELECT json_extract(p.payload_json,'$.workspace.projectId') FROM events p WHERE p.task_id=t.id AND p.kind='task.workspace_prepared' AND p.id<=? ORDER BY p.id DESC LIMIT 1) AS resolved_project_id FROM events e JOIN conversations c ON c.id=e.conversation_id LEFT JOIN tasks t ON t.id=e.task_id WHERE c.owner_id=? AND c.deleted_ms IS NULL AND e.id>? AND e.id<=? AND e.created_ms>=? AND e.created_ms<? AND e.kind IN ("
                    + ",".join("?" for _ in DAILY_KINDS)
                    + ") ORDER BY e.id LIMIT 256",
                    (watermark, owner, cursor, watermark, start, end, *DAILY_KINDS),
                )
                message_ids = [e["message_id"] for e in events if e["message_id"]]
                targets = (
                    rows(
                        db,
                        "SELECT t.origin_message_id,t.intent_json,(SELECT json_extract(p.payload_json,'$.workspace.projectId') FROM events p WHERE p.task_id=t.id AND p.kind='task.workspace_prepared' AND p.id<=? ORDER BY p.id DESC LIMIT 1) AS resolved_project_id FROM tasks t WHERE t.owner_id=? AND t.origin_message_id IN ("
                        + ",".join("?" for _ in message_ids)
                        + ") AND EXISTS(SELECT 1 FROM events e WHERE e.task_id=t.id AND e.kind='task.accepted' AND e.id<=?)",
                        (watermark, owner, *message_ids, watermark),
                    )
                    if message_ids
                    else []
                )
                return events, targets

            events, targets = await self.db.call(page)
            if not events:
                break
            projects = {}
            for target in targets:
                key = (
                    target["resolved_project_id"]
                    or (json.loads(target["intent_json"]).get("target") or {}).get("projectId")
                    or "unassigned"
                )
                projects.setdefault(target["origin_message_id"], set()).add(key)
            for entry in events:
                project = entry["resolved_project_id"] or (
                    (json.loads(entry["intent_json"]).get("target") or {}).get("projectId")
                    if entry["intent_json"]
                    else None
                )
                related = projects.get(entry["message_id"], set())
                scope = project or (next(iter(related)) if len(related) == 1 else "unassigned")
                group = groups.setdefault(
                    scope,
                    {"users": set(), "tasks": set(), "terminal": {}, "sources": {}, "watermark": 0},
                )
                if entry["kind"] in {"message.accepted", "task.intent"} and entry["message_id"]:
                    group["users"].add(entry["message_id"])
                elif entry["kind"] == "task.accepted":
                    group["tasks"].add(entry["task_id"])
                else:
                    group["terminal"][entry["task_id"]] = entry["kind"].split(".", 1)[1]
                group["sources"][entry["kind"]] = entry
                group["watermark"] = max(watermark, entry["id"])
            cursor = events[-1]["id"]

        def commit(db):
            existing = rows(
                db,
                "SELECT d.*,m.state FROM day_summaries d JOIN memory_records m ON m.id=d.memory_id WHERE d.owner_id=? AND d.day_key=? AND d.timezone=?",
                (owner, day_key, zone),
            )
            previous = {item["scope_key"]: item for item in existing}
            result = []
            for scope in sorted(set(groups) | set(previous)):
                group = groups.get(
                    scope,
                    {
                        "users": set(),
                        "tasks": set(),
                        "terminal": {},
                        "sources": {},
                        "watermark": watermark,
                    },
                )
                old = previous.get(scope)
                if old and old["state"] == "deleted":
                    continue
                counts = {"userTurns": len(group["users"]), "tasksCreated": len(group["tasks"])}
                counts.update(
                    {
                        name: sum(value == state for value in group["terminal"].values())
                        for name, state in [
                            ("tasksCompleted", "succeeded"),
                            ("tasksFailed", "failed"),
                            ("tasksCancelled", "cancelled"),
                            ("tasksInterrupted", "interrupted"),
                        ]
                    }
                )
                if old and old["source_watermark"] > watermark:
                    continue
                if old and old["counts_json"] == encoded(counts) and old["state"] == "active":
                    db.execute(
                        "UPDATE day_summaries SET source_watermark=? WHERE id=?",
                        (watermark, old["id"]),
                    )
                    result.append(old["memory_id"])
                    continue
                key = hashlib.sha256(
                    encoded(["daily", owner, day_key, zone, scope]).encode()
                ).hexdigest()
                sources = list(group["sources"].values())
                if row(
                    db,
                    "SELECT 1 FROM memory_tombstones WHERE owner_id=? AND canonical_key=?",
                    (owner, key),
                ):
                    continue
                ident, timestamp = identity(), now_ms()
                revision = (old["revision"] + 1) if old else 1
                title = day_key + " / " + scope
                body = encoded(
                    {
                        "dayKey": day_key,
                        "timezone": zone,
                        "scopeKey": scope,
                        "counts": counts,
                        "sourceWatermark": watermark,
                        "utcStartMs": start,
                        "utcEndMs": end,
                    }
                )
                if old:
                    db.execute(
                        "UPDATE memory_records SET state='superseded',valid_until_ms=?,updated_ms=? WHERE id=?",
                        (timestamp, timestamp, old["memory_id"]),
                    )
                db.execute(
                    "INSERT INTO memory_records(id,owner_id,kind,project_id,day_key,timezone,title,body,search_tokens,canonical_key,state,revision,supersedes_id,valid_from_ms,source_watermark,created_ms,updated_ms) VALUES(?,?,'summary',?,?,?,?,?,?,?,'active',?,?,?,?,?,?)",
                    (
                        ident,
                        owner,
                        None if scope == "unassigned" else scope,
                        day_key,
                        zone,
                        title,
                        body,
                        search_tokens(title + " " + body),
                        key,
                        revision,
                        old["memory_id"] if old else None,
                        timestamp,
                        watermark,
                        timestamp,
                        timestamp,
                    ),
                )
                for source in sources:
                    digest = hashlib.sha256(
                        encoded([source["kind"], source["payload_json"]]).encode()
                    ).hexdigest()
                    db.execute(
                        "INSERT INTO memory_sources(memory_id,source_key,event_id,source_sha256) VALUES(?,?,?,?)",
                        (ident, "event:" + str(source["id"]), source["id"], digest),
                    )
                db.execute(
                    "INSERT INTO day_summaries(id,owner_id,day_key,timezone,scope_key,source_watermark,memory_id,counts_json,revision) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(owner_id,day_key,timezone,scope_key) DO UPDATE SET source_watermark=excluded.source_watermark,memory_id=excluded.memory_id,counts_json=excluded.counts_json,revision=excluded.revision",
                    (
                        old["id"] if old else identity(),
                        owner,
                        day_key,
                        zone,
                        scope,
                        watermark,
                        ident,
                        encoded(counts),
                        revision,
                    ),
                )
                db.execute(
                    "UPDATE owner_versions SET memory_epoch=memory_epoch+1 WHERE owner_id=?",
                    (owner,),
                )
                result.append(ident)
            return result

        return await self.db.call(commit, write=True)
