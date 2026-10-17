"""Bounded target discovery through the unified CLI; no second project/session catalog."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.tools.process import execute


class TargetDirectory:
    def __init__(self, settings):
        self.settings = settings

    async def _query(self, *args):
        try:
            response = await execute(
                [self.settings.cli_bin, *args],
                timeout=5,
                excluded_env=self.settings.provider_key_environments(),
            )
        except (OSError, TimeoutError) as exc:
            raise DomainError("TARGET_DISCOVERY_UNAVAILABLE") from exc
        if response["exitCode"]:
            code = response["stderr"].strip()
            raise DomainError(
                code
                if code
                in {
                    "SESSION_TARGET_AMBIGUOUS",
                    "SESSION_TARGET_NOT_FOUND",
                    "SESSION_OBSERVATION_FAILED",
                }
                else "TARGET_DISCOVERY_UNAVAILABLE"
            )
        try:
            return json.loads(response["stdout"])
        except (ValueError, TypeError) as exc:
            raise DomainError("INVALID_TARGET_RECEIPT") from exc

    @staticmethod
    def _text(entry, key):
        value = entry.get(key)
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise DomainError("INVALID_TARGET_RECEIPT")
        return value

    def _project(self, entry):
        if not isinstance(entry, dict):
            raise DomainError("INVALID_TARGET_RECEIPT")
        return {
            "kind": "project",
            "projectId": self._text(entry, "key"),
            "label": self._text(entry, "name")[:160],
            "archived": entry.get("archived") is True,
        }

    def _session(self, entry):
        if not isinstance(entry, dict):
            raise DomainError("INVALID_TARGET_RECEIPT")
        return {
            "kind": "session",
            "sessionId": self._text(entry, "id"),
            "label": self._text(entry, "label")[:160],
            "state": "live",
        }

    async def search(self, kind, query="", *, offset=0, limit=10):
        if kind == "project":
            payload = await self._query("project", "ls", "--json")
            try:
                entries = payload["data"]["projects"]
            except (KeyError, TypeError) as exc:
                raise DomainError("INVALID_TARGET_RECEIPT") from exc
            project = True
        elif kind == "session":
            entries = await self._query("session", "ls", "--live", "--json")
            project = False
        else:
            raise DomainError("INVALID_TARGET_KIND")
        if not isinstance(entries, list):
            raise DomainError("INVALID_TARGET_RECEIPT")
        query = query.casefold().strip()
        items = []
        for entry in entries:
            item = self._project(entry) if project else self._session(entry)
            identifier = item["projectId" if project else "sessionId"]
            if (
                not query
                or query in identifier.casefold()
                or query in entry.get("name" if project else "label", "").casefold()
            ):
                items.append(item)
        items.sort(key=lambda item: (item["label"].casefold(), encoded(item)))
        packed, size = [], 0
        for item in items[offset : offset + limit]:
            item_size = len(encoded(item).encode())
            if size + item_size > 6000:
                break
            packed.append(item)
            size += item_size
        if not packed and offset < len(items):
            raise DomainError("TARGET_OUTPUT_LIMIT")
        consumed = offset + len(packed)
        return {
            "items": packed,
            "total": len(items),
            "nextOffset": consumed if consumed < len(items) else None,
        }

    async def resolve(self, kind, identifier):
        if kind == "project":
            payload = await self._query("project", "show", identifier, "--json")
            try:
                return self._project(payload["data"])
            except (KeyError, TypeError) as exc:
                raise DomainError("INVALID_TARGET_RECEIPT") from exc
        if kind == "session":
            payload = await self._query("session", "resolve", identifier, "--strict", "--json")
            return self._session(payload)
        raise DomainError("INVALID_TARGET_KIND")
