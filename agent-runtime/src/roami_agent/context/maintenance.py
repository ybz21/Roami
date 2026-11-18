"""Durable idle/day handoff; activate a brief and its archives in one transaction."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from datetime import time as local_time
from zoneinfo import ZoneInfo

import httpx

from roami_agent.context.projection import context_history
from roami_agent.context.retention_policy import POLICY_VERSION, batch_end, complete_groups
from roami_agent.context.retention_policy import source_fingerprint as fingerprint
from roami_agent.context.summary_input import input_budget, read_summary
from roami_agent.context.token_estimate import request_tokens
from roami_agent.context.working_brief import BRIEF_PROMPT, latest, validate_candidate
from roami_agent.memory.daily import event_day
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.retrieval.conversation_search import (
    available,
    index_pending,
    source_hash,
    source_text,
)
from roami_agent.storage.database import row, rows


def daily_cutoff(timestamp, zone_name):
    zone = ZoneInfo(zone_name)
    local = datetime.fromtimestamp(timestamp / 1000, UTC).astimezone(zone)
    day = local.date() - timedelta(days=int(local.time() < local_time(2, 10)))
    return int(datetime.combine(day, local_time.min, zone).timestamp() * 1000)


class ContextMaintenance:
    def __init__(self, database, context, settings):
        self.db, self.context, self.settings = database, context, settings
        self.next_index, self.next_scan = 0, 0
        self.cursor = ""

    async def recover(self):
        await self.db.call(
            lambda db: db.execute(
                "UPDATE jobs SET state='queued' WHERE kind='context.maintain' AND state='running'"
            ),
            write=True,
        )

    async def scan(self, *, force=False):
        clock = time.monotonic()
        if force or clock >= self.next_index:
            await self.db.call(index_pending, write=True)
            self.next_index = clock + 1
        if not self.settings.context_maintenance_enabled or (not force and clock < self.next_scan):
            return
        self.next_scan = clock + 30
        if force:
            self.cursor = ""
        timestamp = now_ms()
        cutoff = daily_cutoff(timestamp, self.settings.memory_timezone)

        def write(db):
            branches = rows(
                db,
                "SELECT b.*,c.owner_id,c.updated_ms AS activity_ms,v.memory_epoch FROM main_conversations h "
                "JOIN conversations c ON c.id=h.conversation_id JOIN branches b ON b.id=c.active_branch_id "
                "JOIN owner_versions v ON v.owner_id=c.owner_id WHERE c.deleted_ms IS NULL AND b.id>? "
                "ORDER BY b.id LIMIT 32",
                (self.cursor,),
            )
            self.cursor = branches[-1]["id"] if branches else ""
            for branch in branches:
                finished = row(
                    db,
                    "SELECT id,created_ms,COALESCE(finished_ms,created_ms) AS finished_ms FROM turns "
                    "WHERE branch_id=? AND state='completed' ORDER BY COALESCE(finished_ms,created_ms) DESC,rowid DESC LIMIT 1",
                    (branch["id"],),
                )
                if not finished:
                    continue
                active_turn = row(
                    db,
                    "SELECT 1 FROM turns WHERE branch_id=? AND state IN ('queued','running') LIMIT 1",
                    (branch["id"],),
                )
                idle = not active_turn and max(finished["finished_ms"], branch["activity_ms"]) <= (
                    timestamp - self.settings.context_idle_seconds * 1000
                )
                closed_day = row(
                    db,
                    "SELECT 1 FROM turns WHERE branch_id=? AND state='completed' AND created_ms<? LIMIT 1",
                    (branch["id"], cutoff),
                )
                if not idle and not closed_day:
                    continue
                reason = "idle" if idle else "daily"
                frontier = "idle" if idle else str(cutoff)
                key = (
                    f"{POLICY_VERSION}:{branch['id']}:{branch['epoch']}:{branch['memory_epoch']}:"
                    f"{finished['id']}:{self.settings.memory_timezone}:{frontier}"
                )
                if row(
                    db,
                    "SELECT 1 FROM jobs WHERE kind='context.maintain' AND state IN ('queued','running') "
                    "AND json_extract(payload_json,'$.branchId')=?",
                    (branch["id"],),
                ):
                    continue
                db.execute(
                    "INSERT OR IGNORE INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                    "VALUES(?,'context.maintain',?,?,?,'queued',?)",
                    (
                        identity(),
                        branch["id"],
                        key,
                        encoded(
                            {
                                "owner": branch["owner_id"],
                                "branchId": branch["id"],
                                "timezone": self.settings.memory_timezone,
                                "reason": reason,
                                "cutoff": cutoff,
                            }
                        ),
                        timestamp,
                    ),
                )

        await self.db.call(write, write=True)

    def _prepare(self, db, job_id):
        job = row(
            db,
            "SELECT * FROM jobs WHERE id=? AND kind='context.maintain' AND state='queued'",
            (job_id,),
        )
        if not job:
            return None
        if not self.settings.context_maintenance_enabled:
            db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
            return None
        payload = json.loads(job["payload_json"])
        branch = row(
            db,
            "SELECT b.*,c.owner_id,c.active_branch_id,v.memory_epoch FROM branches b "
            "JOIN conversations c ON c.id=b.conversation_id JOIN owner_versions v ON v.owner_id=c.owner_id "
            "WHERE b.id=? AND c.owner_id=? AND c.deleted_ms IS NULL",
            (payload["branchId"], payload["owner"]),
        )
        if not branch or branch["id"] != branch["active_branch_id"]:
            db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
            return None
        messages = context_history(db, branch["id"])
        completed = {
            t["id"]
            for t in rows(
                db,
                "SELECT id FROM turns WHERE conversation_id=? AND state='completed'",
                (branch["conversation_id"],),
            )
        }
        previous = latest(db, branch, branch["memory_epoch"], messages)
        covered = previous["source_count"] if previous else 0
        end = batch_end(messages, completed, covered)
        groups = complete_groups(messages, completed)
        if payload["reason"] == "daily":
            end = min(
                end,
                max(
                    (stop for _, _, stop, created in groups if created < payload["cutoff"]),
                    default=0,
                ),
            )
        if end <= covered:
            if any(
                stop > covered and (payload["reason"] != "daily" or created < payload["cutoff"])
                for _, _, stop, created in groups
            ):
                raise DomainError("WORKING_BRIEF_INPUT_TOO_LARGE", 409)
            db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
            return None
        old_items = json.loads(previous["items_json"]) if previous else []
        persistent = [item for item in old_items if item["kind"] != "reference"]
        references = [item for item in old_items if item["kind"] == "reference"][-8:]
        previous_items = [*persistent, *references]
        budget = input_budget(self.context.request_context())
        while end > covered:
            source, incremental = messages[:end], messages[covered:end]
            days = {event_day(m["created_ms"], payload["timezone"]) for m in incremental}
            data = {
                "previousItems": previous_items,
                "days": sorted(days),
                "sources": [
                    {
                        "id": m["id"],
                        "role": "external" if m.get("agent_task_instruction") else m["role"],
                        "status": m["status"],
                        "day": event_day(m["created_ms"], payload["timezone"]),
                        "text": source_text(m),
                    }
                    for m in incremental
                ],
            }
            for entry in data["sources"]:
                if entry["role"] != "user" and len(entry["text"]) > 4000:
                    entry.update(text=entry["text"][:4000], truncated=True)
            prompt = [
                {"role": "system", "content": BRIEF_PROMPT},
                {"role": "user", "content": encoded(data)},
            ]
            if budget is None or request_tokens(prompt, []) <= budget:
                break
            end = max((stop for _, _, stop, _ in groups if covered < stop < end), default=covered)
        if end <= covered:
            raise DomainError("WORKING_BRIEF_INPUT_TOO_LARGE", 409)
        for m in incremental:
            original = row(db, "SELECT * FROM messages WHERE id=?", (m["id"],))
            indexed = row(
                db,
                "SELECT source_sha256 FROM conversation_search_documents WHERE message_id=?",
                (m["id"],),
            )
            if (
                not available(db, branch["owner_id"], original)
                or not indexed
                or indexed["source_sha256"] != source_hash(original)
            ):
                db.execute("UPDATE jobs SET available_ms=? WHERE id=?", (now_ms() + 1000, job_id))
                return None
        db.execute("UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?", (job_id,))
        return job, payload, branch, source, incremental, previous_items, days, prompt

    async def run(self, job_id):
        try:
            prepared = await self.db.call(lambda db: self._prepare(db, job_id), write=True)
        except DomainError as exc:
            error_code = exc.code

            def defer(db):
                job = row(db, "SELECT * FROM jobs WHERE id=? AND state='queued'", (job_id,))
                if job:
                    payload = json.loads(job["payload_json"])
                    payload["error"] = error_code
                    db.execute(
                        "UPDATE jobs SET available_ms=?,payload_json=? WHERE id=?",
                        (now_ms() + 300_000, encoded(payload), job_id),
                    )

            await self.db.call(defer, write=True)
            return
        if not prepared:
            return
        job, payload, branch, source, incremental, previous_items, days, prompt = prepared
        try:
            timeout = self.settings.timeout_for("main")
            async with asyncio.timeout(timeout or None):
                text = await read_summary(self.context.model, prompt)
            items, archives = validate_candidate(
                json.loads(text), previous_items, source, incremental, days
            )

            def activate(db):
                current = row(
                    db,
                    "SELECT b.*,c.active_branch_id,c.deleted_ms,v.memory_epoch FROM branches b "
                    "JOIN conversations c ON c.id=b.conversation_id JOIN owner_versions v ON v.owner_id=c.owner_id WHERE b.id=?",
                    (branch["id"],),
                )
                state = row(db, "SELECT state FROM jobs WHERE id=?", (job_id,))
                stable = context_history(db, branch["id"])[: len(source)]
                if (
                    not current
                    or current["deleted_ms"] is not None
                    or current["epoch"] != branch["epoch"]
                    or current["active_branch_id"] != branch["id"]
                    or current["memory_epoch"] != branch["memory_epoch"]
                    or fingerprint(stable) != fingerprint(source)
                    or state["state"] != "running"
                ):
                    raise DomainError("WORKING_BRIEF_SOURCE_CHANGED", 409)
                for m in stable:
                    if not available(db, branch["owner_id"], m):
                        raise DomainError("WORKING_BRIEF_SOURCE_CHANGED", 409)
                for day, body in archives.items():
                    entries = [
                        m
                        for m in incremental
                        if event_day(m["created_ms"], payload["timezone"]) == day
                    ]
                    db.execute(
                        "INSERT OR IGNORE INTO period_summaries(id,owner_id,branch_id,branch_epoch,memory_epoch,policy_version,day_key,timezone,source_sha256,sources_json,body,created_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            identity(),
                            branch["owner_id"],
                            branch["id"],
                            branch["epoch"],
                            branch["memory_epoch"],
                            POLICY_VERSION,
                            day,
                            payload["timezone"],
                            fingerprint(entries),
                            encoded(
                                [
                                    {
                                        "messageId": m["id"],
                                        "sha256": source_hash(
                                            row(db, "SELECT * FROM messages WHERE id=?", (m["id"],))
                                        ),
                                        "role": m["role"],
                                        "status": m["status"],
                                        "createdMs": m["created_ms"],
                                    }
                                    for m in entries
                                ]
                            ),
                            body,
                            now_ms(),
                        ),
                    )
                brief_id = identity()
                db.execute(
                    "INSERT INTO context_briefs(id,owner_id,branch_id,branch_epoch,memory_epoch,policy_version,source_count,source_sha256,items_json,created_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        brief_id,
                        branch["owner_id"],
                        branch["id"],
                        branch["epoch"],
                        branch["memory_epoch"],
                        POLICY_VERSION,
                        len(source),
                        fingerprint(source),
                        encoded(items),
                        now_ms(),
                    ),
                )
                payload.update(briefId=brief_id, coveredMessages=len(source), completedMs=now_ms())
                payload.pop("error", None)
                db.execute(
                    "UPDATE jobs SET state='done',payload_json=? WHERE id=?",
                    (encoded(payload), job_id),
                )
                if any(
                    stop > len(source)
                    for _, _, stop, _ in complete_groups(
                        context_history(db, branch["id"]),
                        {
                            t["id"]
                            for t in rows(
                                db,
                                "SELECT id FROM turns WHERE branch_id=? AND state='completed'",
                                (branch["id"],),
                            )
                        },
                    )
                ):
                    db.execute(
                        "INSERT OR IGNORE INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'context.maintain',?,?,?,'queued',?)",
                        (
                            identity(),
                            branch["id"],
                            job["dedupe_key"] + ":" + str(len(source)),
                            encoded(payload),
                            now_ms(),
                        ),
                    )

            await self.db.call(activate, write=True)
        except asyncio.CancelledError:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE jobs SET state='queued' WHERE id=? AND state='running'", (job_id,)
                ),
                write=True,
            )
            raise
        except (DomainError, ValueError, TypeError, httpx.HTTPError, TimeoutError) as exc:
            error = exc.code if isinstance(exc, DomainError) else "WORKING_BRIEF_FAILED"
            payload["error"] = error
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE jobs SET state='queued',payload_json=?,available_ms=? WHERE id=? AND state='running'",
                    (
                        encoded(payload),
                        now_ms() + min(3_600_000, 30_000 * 2 ** min(job["attempts"], 7)),
                        job_id,
                    ),
                ),
                write=True,
            )
