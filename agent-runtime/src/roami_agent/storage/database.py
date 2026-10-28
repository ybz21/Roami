"One SQLite writer thread, with the platform maintenance lock held for its lifetime."

import asyncio
import fcntl
import json
import os
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.conversation_events import ConversationEvents
from roami_agent.storage.migrations import SCHEMA_VERSION, initial_schema, upgrade_schema

T = TypeVar("T")


class NativeConnection(sqlite3.Connection):
    native_payloads = None
    event_conversations = None


class Database:
    def __init__(self, path: Path, data_root: Path, *, managed: bool = True):
        self.path, self.data_root, self.managed = path, data_root, managed
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-db")
        self.connection = None
        self.locks = []
        self.closed = False
        self.pending = 0
        self.instance_paths = None
        self.conversation_events = ConversationEvents()

    async def open(self):
        try:
            await self.call(self._open)
        except BaseException:
            await self.close()
            raise

    def _open(self, _):
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_root = self.data_root / "locks"
        lock_root.mkdir(exist_ok=True, mode=0o700)
        for name, mode in [("storage", fcntl.LOCK_SH), ("agent-runtime", fcntl.LOCK_EX)]:
            lock = os.open(lock_root / f"{name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(lock, mode | fcntl.LOCK_NB)
            except OSError:
                os.close(lock)
                raise DomainError("STORAGE_BUSY", 503) from None
            self.locks.append(lock)
        if self.managed:
            layout = json.loads((self.data_root / "storage-layout.json").read_text())
            if (self.data_root / "storage-migration.json").exists():
                raise DomainError("STORAGE_RECOVERY_REQUIRED", 503)
            self.instance_paths = dict(layout["paths"])
            db_root = Path(layout["paths"]["databaseRoot"])
            catalog = json.loads((db_root / "catalog.json").read_text())
            if catalog["instanceId"] != layout["instanceId"]:
                raise DomainError("STORAGE_INSTANCE_CONFLICT", 503)
            entry = next((d for d in catalog["databases"] if d["id"] == "agent-runtime"), None)
            if (
                not entry
                or entry["kind"] != "agent"
                or entry["owner"] != "python-agent"
                or (db_root / entry["path"]).resolve() != self.path.resolve()
            ):
                raise DomainError("AGENT_DATABASE_NOT_REGISTERED", 503)
            if entry["state"] == "ready" and not self.path.exists():
                raise DomainError("DATABASE_MISSING", 503)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(self.path, isolation_level=None, factory=NativeConnection)
        os.chmod(self.path, 0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("PRAGMA foreign_keys=ON; PRAGMA busy_timeout=1000;")
        has_schema = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='schema_meta'"
        ).fetchone()
        if not has_schema:
            if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise DomainError("AGENT_SCHEMA_UNKNOWN", 503)
            schema = initial_schema()
            # executescript commits beforehand; migration contents are one explicit transaction.
            pragmas, ddl = schema.split("CREATE TABLE schema_meta", 1)
            self.connection.executescript(pragmas)
            self.connection.executescript(
                "BEGIN IMMEDIATE; CREATE TABLE schema_meta" + ddl + "COMMIT;"
            )
        version = self.connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
        if not isinstance(version, int) or not 1 <= version <= SCHEMA_VERSION:
            raise DomainError("AGENT_SCHEMA_UNSUPPORTED", 503)
        self.connection.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;")
        upgrade_schema(self.connection, version)
        from roami_agent.storage.native_payloads import NativePayloads

        home = (self.instance_paths or {}).get("homeRoot") or self.data_root
        if self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='native_storage_config'"
        ).fetchone():
            key = self.connection.execute(
                "SELECT reference_key FROM native_storage_config WHERE id=1"
            ).fetchone()[0]
            self.connection.native_payloads = NativePayloads(
                Path(home) / "agents" / "native", bytes.fromhex(key)
            )
        self.connection.create_function(
            "native_content",
            1,
            self.connection.native_payloads.resolve
            if self.connection.native_payloads
            else lambda value: value,
        )
        from roami_agent.storage.native_public_record import public_json

        self.connection.create_function("native_public", 1, public_json)

    async def call(self, fn: Callable[[sqlite3.Connection], T], *, write: bool = False) -> T:
        if self.closed:
            raise DomainError("RUNTIME_CLOSED", 503)
        if self.pending >= 256:
            raise DomainError("WRITER_BUSY", 503)
        self.pending += 1
        loop = asyncio.get_running_loop()

        def execute():
            try:
                if write:
                    self.connection.execute("BEGIN IMMEDIATE")
                    self.connection.event_conversations = set()
                result = fn(self.connection)
                if write:
                    self.connection.execute("COMMIT")
                    if self.connection.event_conversations:
                        loop.call_soon_threadsafe(
                            self.conversation_events.publish, self.connection.event_conversations
                        )
                return result
            except BaseException:
                if write and self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise
            finally:
                if write:
                    self.connection.event_conversations = None

        future = loop.run_in_executor(self.pool, execute)
        # A cancelled HTTP request must not release capacity while its transaction is running.
        future.add_done_callback(lambda _: setattr(self, "pending", self.pending - 1))
        return await asyncio.shield(future)

    async def close(self):
        if self.closed:
            return
        self.closed = True

        def finish():
            if self.connection:
                self.connection.close()
            for lock in reversed(self.locks):
                os.close(lock)
            self.locks.clear()

        await asyncio.get_running_loop().run_in_executor(self.pool, finish)
        self.pool.shutdown(wait=True)


def hydrated(connection, value):
    result = dict(value)
    resolver = getattr(connection, "native_payloads", None)
    if resolver:
        for key, content in result.items():
            if key.endswith("_json"):
                result[key] = resolver.resolve(content)
    return result


def row(connection, sql: str, args=()):
    value = connection.execute(sql, args).fetchone()
    return hydrated(connection, value) if value else None


def rows(connection, sql: str, args=()):
    return [hydrated(connection, r) for r in connection.execute(sql, args)]


def event(connection, conversation_id: str, kind: str, payload, *, key=None, **refs) -> int:
    fields = {
        "conversation_id": conversation_id,
        "kind": kind,
        "payload_json": encoded(payload),
        "event_key": key or identity(),
        "created_ms": now_ms(),
        **refs,
    }
    keys = ",".join(fields)
    values = ",".join("?" for _ in fields)
    cursor = connection.execute(
        f"INSERT INTO events ({keys}) VALUES ({values})", tuple(fields.values())
    ).lastrowid
    if getattr(connection, "event_conversations", None) is not None:
        connection.event_conversations.add(conversation_id)
    return cursor
