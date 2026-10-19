"""Bounded target discovery through the unified CLI; no second project/session catalog."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.tools.process import execute


class TargetDirectory:
    def __init__(self, settings, dispatches=None):
        self.settings, self.dispatches = settings, dispatches

    async def send(self, session_id, text, key, *, binding=None):
        dispatch = None
        if self.dispatches and binding:
            dispatch = await self.dispatches.prepare(session_id, text, key, binding)
            if dispatch["delivery_state"] == "failed":
                raise DomainError(json.loads(dispatch["delivery_receipt_json"])["errorCode"])
            if dispatch["delivery_receipt_json"]:
                return json.loads(dispatch["delivery_receipt_json"])
            if dispatch["delivery_state"] in {"unknown", "failed"}:
                raise DomainError("TOOL_OUTCOME_UNKNOWN")
            text = dispatch["prompt"]
        try:
            result = await self._send(session_id, text, key)
        except BaseException as exc:
            if dispatch:
                code = (
                    exc.code
                    if isinstance(exc, DomainError)
                    and exc.code
                    in {
                        "SESSION_TARGET_AMBIGUOUS",
                        "SESSION_TARGET_NOT_FOUND",
                        "SESSION_PANE_AMBIGUOUS",
                        "MESSAGE_KEY_CONFLICT",
                        "INVALID_SESSION_MESSAGE",
                    }
                    else None
                )
                await self.dispatches.record_delivery(dispatch, error_code=code)
            raise
        if dispatch:
            result.update(dispatchId=dispatch["id"], replyExpected=True, replyProtocol="roami-cli")
            await self.dispatches.record_delivery(dispatch, result)
        return result

    async def _send(self, session_id, text, key):
        try:
            response = await execute(
                [self.settings.cli_bin, "agent", "execution", "send-message", "--file", "-"],
                timeout=15,
                excluded_env=self.settings.provider_key_environments(),
                input_data=encoded({"key": key, "sessionId": session_id, "text": text}).encode(),
            )
        except (TimeoutError, OSError) as exc:
            raise DomainError("TOOL_OUTCOME_UNKNOWN") from exc
        if response["exitCode"]:
            code = response.get("stderr", "").strip()
            raise DomainError(
                code
                if code
                in {
                    "SESSION_TARGET_AMBIGUOUS",
                    "SESSION_TARGET_NOT_FOUND",
                    "SESSION_PANE_AMBIGUOUS",
                    "MESSAGE_KEY_CONFLICT",
                    "INVALID_SESSION_MESSAGE",
                }
                else "TOOL_OUTCOME_UNKNOWN"
            )
        try:
            receipt = json.loads(response["stdout"])
            if receipt["state"] != "delivered" or receipt["outcomeKnown"] is not True:
                raise DomainError("TOOL_OUTCOME_UNKNOWN")
            return {
                "sessionId": receipt["session"],
                "state": "delivered",
                "executionTracked": False,
            }
        except (ValueError, TypeError, KeyError) as exc:
            raise DomainError("TOOL_OUTCOME_UNKNOWN") from exc

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
            try:
                error = json.loads(response.get("stdout", ""))["error"]["code"]
            except (ValueError, TypeError, KeyError):
                error = None
            if error == "UNAUTHORIZED":
                raise DomainError("ROAMI_CLI_AUTH_REQUIRED")
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

    async def overview(self):
        payload = await self._query("project", "ls", "--json")
        try:
            projects, loose = payload["data"]["projects"], payload["data"]["loose"]
        except (KeyError, TypeError) as exc:
            raise DomainError("INVALID_TARGET_RECEIPT") from exc
        if not isinstance(projects, list) or not isinstance(loose, list):
            raise DomainError("INVALID_TARGET_RECEIPT")
        total = dormant = archived = 0
        for project in projects:
            self._project(project)
            count, sleeping = project.get("sessions"), project.get("dormant")
            if type(count) is not int or type(sleeping) is not int or not 0 <= sleeping <= count:
                raise DomainError("INVALID_TARGET_RECEIPT")
            total += count
            dormant += sleeping
            archived += project.get("archived") is True
        loose_dormant = 0
        for session in loose:
            if not isinstance(session, dict) or session.get("state", "live") not in {
                "",
                "live",
                "dormant",
            }:
                raise DomainError("INVALID_TARGET_RECEIPT")
            loose_dormant += session.get("state") == "dormant"
        return {
            "scope": "current_node",
            "projects": len(projects),
            "archivedProjects": archived,
            "projectSessions": total,
            "looseSessions": len(loose),
            "sessions": total + len(loose),
            "liveSessions": total - dormant + len(loose) - loose_dormant,
            "dormantSessions": dormant + loose_dormant,
        }

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

    async def search(self, kind, query="", *, offset=0, limit=10, project_id=None):
        if project_id and kind != "session":
            raise DomainError("INVALID_TARGET_KIND")
        if kind == "project":
            payload = await self._query("project", "ls", "--json")
            try:
                entries = payload["data"]["projects"]
            except (KeyError, TypeError) as exc:
                raise DomainError("INVALID_TARGET_RECEIPT") from exc
            project = True
        elif kind == "session":
            if project_id:
                payload = await self._query("project", "sessions", project_id, "--json")
                try:
                    raw = payload["data"]["sessions"]
                    if not isinstance(raw, list):
                        raise DomainError("INVALID_TARGET_RECEIPT")
                    entries = []
                    for entry in raw:
                        if not isinstance(entry, dict):
                            raise DomainError("INVALID_TARGET_RECEIPT")
                        if entry.get("state", "live") not in {"", "live", "dormant"}:
                            raise DomainError("INVALID_TARGET_RECEIPT")
                        if entry.get("state") == "dormant":
                            continue
                        name = self._text(entry, "name")
                        entries.append(
                            {
                                "id": name,
                                "label": entry.get("label") or name,
                                "agent": entry.get("agent", ""),
                            }
                        )
                except (KeyError, TypeError) as exc:
                    raise DomainError("INVALID_TARGET_RECEIPT") from exc
            else:
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
            if project_id:
                item["projectId"] = project_id
                if entry.get("agent") in {"codex", "claude"}:
                    item["executor"] = entry["agent"]
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
