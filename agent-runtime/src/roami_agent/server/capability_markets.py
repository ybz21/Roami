"""Node-owned marketplace configuration and bounded, on-demand catalog requests."""

import asyncio
import copy
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.server import market_catalogs
from roami_agent.server.market_installations import MarketInstallations
from roami_agent.server.model_settings import ModelSettings


class CapabilityMarkets:
    def __init__(self, runtime):
        self.runtime = runtime
        self.path = Path(runtime.db.data_root) / "agents" / "capability-markets.json"
        self.lock = asyncio.Lock()
        self.requests = asyncio.Semaphore(4)
        self.cache, self.inflight = {}, {}
        self.installations = MarketInstallations(self)
        self.sources = copy.deepcopy(market_catalogs.DEFAULT_SOURCES)
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size > 32000
            ):
                raise DomainError("MARKET_PRIVATE_FILE_REQUIRED", 503)
            try:
                self.sources = self.validate(json.loads(self.path.read_text()))
            except (ValueError, OSError, DomainError):
                raise DomainError("INVALID_MARKET_SOURCE", 503) from None

    @staticmethod
    def validate(sources):
        if not isinstance(sources, list) or not 1 <= len(sources) <= 16:
            raise DomainError("INVALID_MARKET_SOURCE")
        names, result = set(), []
        for source in sources:
            if not isinstance(source, dict) or set(source) != {
                "id",
                "name",
                "provider",
                "url",
                "enabled",
            }:
                raise DomainError("INVALID_MARKET_SOURCE")
            if (
                not isinstance(source["id"], str)
                or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", source["id"])
                or source["id"] in names
            ):
                raise DomainError("INVALID_MARKET_SOURCE")
            if (
                not isinstance(source["name"], str)
                or not 1 <= len(source["name"].strip()) <= 80
                or not isinstance(source["provider"], str)
                or source["provider"] not in market_catalogs.PROVIDER_KINDS
                or type(source["enabled"]) is not bool
            ):
                raise DomainError("INVALID_MARKET_SOURCE")
            names.add(source["id"])
            result.append({**source, "url": market_catalogs.public_url(source["url"])})
        if len(json.dumps(result).encode()) > 32000:
            raise DomainError("INVALID_MARKET_SOURCE")
        return result

    def view(self, owner):
        ModelSettings.owner(owner)
        return {"sources": copy.deepcopy(self.sources)}

    async def save(self, owner, payload):
        ModelSettings.owner(owner)
        if not isinstance(payload, dict) or set(payload) != {"sources"}:
            raise DomainError("INVALID_MARKET_SOURCE")
        updated = self.validate(payload["sources"])
        async with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            info = self.path.parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("MARKET_PRIVATE_FILE_REQUIRED", 503)
            descriptor, temporary = tempfile.mkstemp(prefix=".markets-", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w") as output:
                    os.fchmod(output.fileno(), 0o600)
                    json.dump(updated, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.sources = updated
            self.cache.clear()
        return self.view(owner)

    def source(self, owner, source_id):
        ModelSettings.owner(owner)
        source = next((source for source in self.sources if source["id"] == source_id), None)
        if not source or not source["enabled"]:
            raise DomainError("MARKET_SOURCE_DISABLED", 409)
        return dict(source)

    async def _request(self, key, operation):
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            return copy.deepcopy(cached[1])
        if key not in self.inflight:
            if len(self.inflight) >= 16:
                raise DomainError("MARKET_RATE_LIMITED", 429)

            async def run():
                try:
                    async with self.requests, asyncio.timeout(90):
                        return await operation()
                except (TimeoutError, KeyError, IndexError, TypeError, ValueError, AttributeError):
                    raise DomainError("MARKET_UNAVAILABLE", 502) from None

            self.inflight[key] = asyncio.create_task(run())

            def settled(task):
                if not task.cancelled():
                    task.exception()
                if self.inflight.get(key) is task:
                    self.inflight.pop(key, None)

            self.inflight[key].add_done_callback(settled)
        task = self.inflight[key]
        try:
            result = await asyncio.shield(task)
            if len(self.cache) >= 32:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = (time.monotonic() + 60, result)
            return copy.deepcopy(result)
        finally:
            if task.done() and self.inflight.get(key) is task:
                self.inflight.pop(key, None)

    async def search(self, owner, source_id, query, cursor=""):
        source = self.source(owner, source_id)
        if (
            not isinstance(query, str)
            or not 1 <= len(query.strip()) <= 200
            or not isinstance(cursor, str)
            or len(cursor) > 1000
        ):
            raise DomainError("INVALID_MARKET_QUERY")
        if source["provider"] == "npm" and cursor and (not cursor.isdigit() or int(cursor) > 10000):
            raise DomainError("INVALID_MARKET_QUERY")
        key = (json.dumps(source, sort_keys=True), "search", query.strip(), cursor)
        return await self._request(
            key, lambda: market_catalogs.search(source, query.strip(), cursor)
        )

    async def preview(self, owner, payload):
        if (
            not isinstance(payload, dict)
            or set(payload) != {"source", "id", "version"}
            or any(not isinstance(value, str) or len(value) > 1000 for value in payload.values())
            or not payload["id"]
        ):
            raise DomainError("INVALID_MARKET_QUERY")
        source = self.source(owner, payload["source"])
        key = (json.dumps(source, sort_keys=True), "preview", payload["id"], payload["version"])
        return await self._request(
            key, lambda: market_catalogs.preview(source, payload["id"], payload["version"])
        )

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.inflight.clear()
        self.installations.receipts.clear()
