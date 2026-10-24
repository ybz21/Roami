"""Native session registry, transactional journal projection and lossless archives."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows
from roami_agent.storage.native_session_files import NativeSessionFiles
from roami_agent.storage.native_session_registry import backfill
from roami_agent.storage.transcript_repository import owned


class NativeSessions:
    def __init__(self, database):
        self.db = database
        home = (database.instance_paths or {}).get("homeRoot") or database.data_root
        self.root = Path(home) / "agents" / "native"
        self.files = NativeSessionFiles(self.root)
        self.lock = asyncio.Lock()

    async def recover(self):
        await self.db.call(backfill, write=True)
        await self.flush()

    @staticmethod
    def _get(db, owner, ident):
        value = row(
            db,
            "SELECT n.*,t.parent_task_id,t.target_json,t.intent_json,t.state AS task_state,t.revision,t.origin_message_id,(SELECT state FROM task_session_closures WHERE task_id=t.id) AS session_closure FROM native_sessions n JOIN tasks t ON t.id=n.task_id JOIN messages m ON m.id=t.origin_message_id JOIN conversations c ON c.id=t.origin_conversation_id WHERE n.id=? AND n.owner_id=? AND m.deleted_ms IS NULL AND c.deleted_ms IS NULL AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=n.owner_id AND o.message_id=t.origin_message_id)",
            (ident, owner),
        )
        if not value:
            raise DomainError("NATIVE_SESSION_NOT_FOUND", 404)
        owned(db, owner, value["conversation_id"])
        return value

    async def list(self, owner, *, project_id=None):
        def read(db):
            result = []
            for entry in rows(
                db,
                "SELECT n.id FROM native_sessions n JOIN tasks t ON t.id=n.task_id WHERE n.owner_id=? AND NOT EXISTS(SELECT 1 FROM task_session_closures x WHERE x.task_id=t.id AND x.state='closed') AND (? IS NULL OR COALESCE(json_extract(t.target_json,'$.projectId'),json_extract(t.intent_json,'$.target.projectId'))=?) ORDER BY t.updated_ms DESC LIMIT 200",
                (owner, project_id, project_id),
            ):
                try:
                    value = self._get(db, owner, entry["id"])
                except DomainError:
                    continue
                metadata = self.metadata(value)
                metadata["title"] = (
                    json.loads(value["intent_json"]).get("title")
                    or json.loads(value["intent_json"]).get("goal", "")[:100]
                )
                result.append(metadata)
            return result

        return await self.db.call(read)

    async def conversation(self, owner, ident, *, before=None, limit=80):
        def read(db):
            session = self._get(db, owner, ident)
            messages = rows(
                db,
                "SELECT * FROM messages m WHERE m.conversation_id=? AND m.branch_id=? AND m.deleted_ms IS NULL AND m.status!='deleted' AND m.role IN ('user','assistant') AND (? IS NULL OR m.seq<?) AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id) ORDER BY m.seq DESC LIMIT ?",
                (
                    session["conversation_id"],
                    session["branch_id"],
                    before,
                    before,
                    owner,
                    limit + 1,
                ),
            )
            has_more = len(messages) > limit
            messages = list(reversed(messages[:limit]))
            content = [(m, json.loads(m["content_json"])) for m in messages]
            revisions = {
                value.get("taskRevision")
                for _, value in content
                if isinstance(value.get("taskRevision"), int)
            }
            steering = {}
            if revisions:
                for item in rows(
                    db,
                    "SELECT payload_json FROM jobs WHERE kind='task.steer' AND aggregate_id=? AND json_extract(payload_json,'$.appliedRevision') IN ("
                    + ",".join("?" for _ in revisions)
                    + ")",
                    (session["task_id"], *sorted(revisions)),
                ):
                    payload = json.loads(item["payload_json"])
                    steering[payload["appliedRevision"]] = payload["text"]
            visible = [
                dict(
                    m,
                    content={
                        **value,
                        "text": value.get("displayText")
                        or steering.get(value.get("taskRevision"))
                        or value.get("text", ""),
                    },
                )
                for m, value in content
            ]
            return {
                "conversation": owned(db, owner, session["conversation_id"]),
                "branchId": session["branch_id"],
                "messages": visible,
                "turns": rows(
                    db,
                    "SELECT id,state FROM turns WHERE branch_id=? ORDER BY created_ms DESC LIMIT 20",
                    (session["branch_id"],),
                ),
                "activities": [],
                "snapshotCursor": 0,
                "before": messages[0]["seq"] if has_more and messages else None,
            }

        return await self.db.call(read)

    def metadata(self, session):
        target = json.loads(session.get("target_json") or "null") or json.loads(
            session["intent_json"]
        ).get("target", {})
        return {
            "schemaVersion": 1,
            "nativeSessionId": session["id"],
            "taskId": session["task_id"],
            "conversationId": session["conversation_id"],
            "branchId": session["branch_id"],
            "parentNativeSessionId": session["parent_session_id"],
            "parentConversationId": session["parent_conversation_id"],
            "rootConversationId": session["root_conversation_id"],
            "parentTaskId": session["parent_task_id"],
            "nodeId": target.get("nodeId", "local"),
            "projectId": target.get("projectId"),
            "workspaceId": target.get("workspaceId"),
            "directory": target.get("workdir") or target.get("directory"),
            "taskState": session["task_state"],
            "lifecycle": "closed"
            if session.get("session_closure") == "closed"
            else "closing"
            if session.get("session_closure") in {"closing", "unknown"}
            else "open",
            "revision": session["revision"],
            "createdAt": datetime.fromtimestamp(session["created_ms"] / 1000, UTC).isoformat(),
            "storageDirectory": str(self.root / session["id"]),
            "committedSeq": session["last_seq"],
            "projectedSeq": session["flushed_seq"],
            "archivedSeq": session["archived_seq"],
            "archiveError": session["archive_error"],
        }

    async def get(self, owner, ident):
        return self.metadata(await self.db.call(lambda db: self._get(db, owner, ident)))

    @staticmethod
    def _record(entry):
        return {
            "schemaVersion": 1,
            "nativeSessionId": entry["session_id"],
            "seq": entry["seq"],
            "eventId": entry["event_id"],
            "type": entry["kind"],
            "entityId": entry["entity_id"],
            "at": datetime.fromtimestamp(entry["created_ms"] / 1000, UTC).isoformat(),
            "payload": json.loads(entry["payload_json"]),
        }

    async def flush(self):
        async with self.lock:
            pending = await self.db.call(
                lambda db: rows(
                    db,
                    "SELECT session_id FROM native_session_events WHERE payload_json IS NOT NULL GROUP BY session_id ORDER BY MIN(created_ms) LIMIT 20",
                )
            )
            for item in pending:
                ident = item["session_id"]
                try:
                    session, entries = await self.db.call(
                        lambda db, ident=ident: (
                            row(
                                db,
                                "SELECT n.*,t.parent_task_id,t.target_json,t.intent_json,t.state AS task_state,t.revision,(SELECT state FROM task_session_closures WHERE task_id=t.id) AS session_closure FROM native_sessions n JOIN tasks t ON t.id=n.task_id WHERE n.id=?",
                                (ident,),
                            ),
                            rows(
                                db,
                                "SELECT * FROM native_session_events WHERE session_id=? AND payload_json IS NOT NULL ORDER BY seq LIMIT 200",
                                (ident,),
                            ),
                        )
                    )
                    records = [self._record(entry) for entry in entries]
                    written = await asyncio.to_thread(
                        self.files.append, ident, records, self.metadata(session)
                    )

                    def commit(db, written=written, ident=ident):
                        for seq, digest, _ in written:
                            db.execute(
                                "UPDATE native_session_events SET payload_json=NULL,record_sha256=? WHERE session_id=? AND seq=?",
                                (digest, ident, seq),
                            )
                        if written:
                            db.execute(
                                "UPDATE native_sessions SET flushed_seq=MAX(flushed_seq,?),unarchived_bytes=unarchived_bytes+?,archive_error=NULL WHERE id=?",
                                (written[-1][0], sum(size for _, _, size in written), ident),
                            )

                    await self.db.call(commit, write=True)
                except (DomainError, OSError, ValueError) as exc:
                    code = (
                        exc.code if isinstance(exc, DomainError) else "NATIVE_JOURNAL_UNAVAILABLE"
                    )
                    await self.db.call(
                        lambda db, ident=ident, code=code: db.execute(
                            "UPDATE native_sessions SET archive_error=? WHERE id=?",
                            (
                                code,
                                ident,
                            ),
                        ),
                        write=True,
                    )

    async def events(self, owner, ident, after=0, limit=100):
        await self.db.call(lambda db: self._get(db, owner, ident))
        await self.flush()
        async with self.lock:
            session, segments = await self.db.call(
                lambda db: (
                    self._get(db, owner, ident),
                    rows(
                        db,
                        "SELECT * FROM native_session_segments WHERE session_id=? ORDER BY first_seq",
                        (ident,),
                    ),
                )
            )
            if session["archive_error"]:
                raise DomainError(session["archive_error"], 503)
            try:
                values = await asyncio.to_thread(self.files.records, ident, segments, after, limit)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise DomainError("NATIVE_JOURNAL_UNAVAILABLE", 503) from exc

            def validate(db):
                self._get(db, owner, ident)
                visible = []
                for record in values:
                    expected = row(
                        db,
                        "SELECT record_sha256 FROM native_session_events WHERE session_id=? AND seq=?",
                        (ident, record["seq"]),
                    )
                    if (
                        record["nativeSessionId"] != ident
                        or not expected
                        or hashlib.sha256((encoded(record) + "\n").encode()).hexdigest()
                        != expected["record_sha256"]
                    ):
                        raise DomainError("NATIVE_JOURNAL_CORRUPT", 503)
                    if record["type"].startswith("message.") and not row(
                        db,
                        "SELECT id FROM messages m WHERE id=? AND deleted_ms IS NULL AND status!='deleted' AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
                        (record["entityId"], owner),
                    ):
                        continue
                    visible.append(record)
                return visible

            visible = await self.db.call(validate)
            if not values and after < session["flushed_seq"]:
                raise DomainError("NATIVE_JOURNAL_MISSING", 503)
            return {
                "items": visible,
                "nextSeq": values[-1]["seq"] if values else after,
                "committedSeq": session["last_seq"],
                "projectedSeq": session["flushed_seq"],
            }

    async def maintain(self):
        await self.flush()
        candidates = await self.db.call(
            lambda db: rows(
                db,
                "SELECT id,owner_id FROM native_sessions n WHERE flushed_seq>archived_seq AND (unarchived_bytes>=33554432 OR EXISTS(SELECT 1 FROM native_session_events e WHERE e.session_id=n.id AND e.seq>n.archived_seq AND e.created_ms<?) OR EXISTS(SELECT 1 FROM task_session_closures c WHERE c.task_id=n.task_id AND c.state='closed')) LIMIT 5",
                (now_ms() - 86400000,),
            )
        )
        for session in candidates:
            try:
                await self.archive(session["owner_id"], session["id"])
            except DomainError as exc:
                if exc.status != 404:
                    raise

    async def archive(self, owner, ident, *, through=None):
        await self.flush()
        async with self.lock:
            session = await self.db.call(lambda db: self._get(db, owner, ident))
            through = min(
                through if through is not None else session["flushed_seq"], session["flushed_seq"]
            )
            if through <= session["archived_seq"]:
                return None
            segment = await asyncio.to_thread(
                self.files.seal, ident, through, session["archived_seq"]
            )
            if not segment:
                return None
            verified = await asyncio.to_thread(
                self.files.archive_bytes,
                ident,
                {
                    "filename": segment["filename"],
                    "sha256": segment["sha256"],
                    "raw_sha256": segment["rawSha256"],
                    "raw_bytes": segment["rawBytes"],
                },
            )

            def validate_segment(db):
                expected_seq = session["archived_seq"] + 1
                for line in verified.splitlines(keepends=True):
                    record = json.loads(line)
                    expected = row(
                        db,
                        "SELECT record_sha256 FROM native_session_events WHERE session_id=? AND seq=?",
                        (ident, record["seq"]),
                    )
                    if (
                        record["seq"] != expected_seq
                        or record["nativeSessionId"] != ident
                        or not expected
                        or hashlib.sha256(line).hexdigest() != expected["record_sha256"]
                    ):
                        raise DomainError("NATIVE_ARCHIVE_CORRUPT", 503)
                    expected_seq += 1
                if expected_seq != segment["lastSeq"] + 1:
                    raise DomainError("NATIVE_ARCHIVE_CORRUPT", 503)

            await self.db.call(validate_segment)
            await self.db.call(
                lambda db: (
                    db.execute(
                        "INSERT INTO native_session_segments(session_id,first_seq,last_seq,filename,sha256,raw_sha256,raw_bytes,compressed_bytes,created_ms) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id,first_seq) DO UPDATE SET last_seq=excluded.last_seq WHERE native_session_segments.sha256=excluded.sha256",
                        (
                            ident,
                            segment["firstSeq"],
                            segment["lastSeq"],
                            segment["filename"],
                            segment["sha256"],
                            segment["rawSha256"],
                            segment["rawBytes"],
                            segment["compressedBytes"],
                            now_ms(),
                        ),
                    ),
                    db.execute(
                        "UPDATE native_sessions SET archived_seq=?,unarchived_bytes=MAX(0,unarchived_bytes-?) WHERE id=?",
                        (segment["lastSeq"], segment["rawBytes"], ident),
                    ),
                ),
                write=True,
            )
            await self._offload(ident, segment)
            segments = await self.db.call(
                lambda db: rows(
                    db,
                    "SELECT * FROM native_session_segments WHERE session_id=? ORDER BY first_seq",
                    (ident,),
                )
            )
            await asyncio.to_thread(
                self.files.trim,
                ident,
                segment["lastSeq"],
                {"schemaVersion": 1, "segments": segments},
            )
            current = await self.get(owner, ident)
            await asyncio.to_thread(self.files.metadata, ident, current)
            return segment

    async def _offload(self, ident, segment):
        descriptor = {
            "filename": segment["filename"],
            "sha256": segment["sha256"],
            "raw_sha256": segment["rawSha256"],
            "raw_bytes": segment["rawBytes"],
        }
        raw = await asyncio.to_thread(self.files.archive_bytes, ident, descriptor)
        records = await asyncio.to_thread(lambda: [json.loads(line) for line in raw.splitlines()])

        def commit(db, batch):
            session = row(db, "SELECT * FROM native_sessions WHERE id=?", (ident,))
            if row(
                db,
                "SELECT id FROM turns WHERE branch_id=? AND state IN ('queued','running') LIMIT 1",
                (session["branch_id"],),
            ):
                return
            protected = {
                r["id"]
                for r in rows(
                    db,
                    "SELECT id FROM turns WHERE branch_id=? ORDER BY created_ms DESC LIMIT 2",
                    (session["branch_id"],),
                )
            }
            for record in batch:
                event = row(
                    db,
                    "SELECT record_sha256 FROM native_session_events WHERE session_id=? AND seq=?",
                    (ident, record["seq"]),
                )
                if (
                    not event
                    or hashlib.sha256((encoded(record) + "\n").encode()).hexdigest()
                    != event["record_sha256"]
                ):
                    raise DomainError("NATIVE_ARCHIVE_CORRUPT", 503)
                if record["type"] == "message.committed":
                    table, field, payload = "messages", "content_json", "content"
                elif record["type"] in {"tool.succeeded", "tool.failed", "tool.cancelled"}:
                    table, field, payload = "tool_calls", "arguments_json", "arguments"
                else:
                    continue
                source = row(
                    db,
                    f"SELECT * FROM {table} WHERE id=? AND created_ms<? AND json_type({field},'$._nativePayload') IS NULL",
                    (record["entityId"], now_ms() - 7 * 86400000),
                )
                if not source or source["turn_id"] in protected or payload not in record["payload"]:
                    continue
                if source[field] != encoded(record["payload"][payload]):
                    continue
                reference = db.native_payloads.reference(ident, segment, record, payload)
                if len(reference.encode()) >= len(source[field].encode()):
                    continue
                db.execute(
                    f"UPDATE {table} SET {field}=? WHERE id=? AND {field}=?",
                    (reference, source["id"], source[field]),
                )

        for offset in range(0, len(records), 100):
            await self.db.call(
                lambda db, offset=offset: commit(db, records[offset : offset + 100]), write=True
            )
