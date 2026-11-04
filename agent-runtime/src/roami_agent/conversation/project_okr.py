"""Registered project operations for independent, project-bound goal conversations."""

import json

from roami_agent.protocol.errors import DomainError, public_error_code
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import owned
from roami_agent.tools.process import execute


def project_id(value):
    if not isinstance(value, str) or not value.strip() or value.startswith("-") or "\0" in value:
        raise DomainError("INVALID_OKR_PROJECT_ID")
    return value


async def request(settings, argv, body=None):
    result = await execute(
        [settings.cli_bin, *argv, *(["--file", "-"] if body is not None else []), "--json"],
        input_data=encoded(body).encode() if body is not None else None,
        excluded_env=settings.provider_key_environments(),
        timeout=15,
        max_bytes=2_000_000,
    )
    try:
        value = json.loads(result["stdout"])
        if result["exitCode"]:
            problem = value.get("error")
            code = public_error_code(problem.get("code") if isinstance(problem, dict) else problem)
            raise DomainError(code or "PROJECT_OKR_UNAVAILABLE", 409)
        return value["data"]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise DomainError("PROJECT_OKR_UNAVAILABLE", 503) from exc


async def registered_project(settings, value):
    entry = await request(settings, ["project", "show", project_id(value)])
    if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
        raise DomainError("PROJECT_OKR_UNAVAILABLE", 503)
    return project_id(entry["key"])


async def operation(settings, pid, action, payload=None):
    if action not in {"show", "save", "collect", "record", "review", "sync", "memory"}:
        raise DomainError("INVALID_OKR_OPERATION")
    value = await request(settings, ["project", "okr", action, project_id(pid)], payload)
    if value is not None and not isinstance(value, dict):
        raise DomainError("PROJECT_OKR_UNAVAILABLE", 503)
    return value


async def bound_project(database, binding):
    if binding.get("taskId") or binding.get("executionRunId") or binding.get("role") == "worker":
        raise DomainError("PROJECT_OKR_MAIN_REQUIRED", 403)

    def read(db):
        owned(db, binding["owner"], binding["conversation"])
        value = row(
            db,
            "SELECT project_id FROM project_okr_conversations WHERE conversation_id=? AND owner_id=?",
            (binding["conversation"], binding["owner"]),
        )
        if not value:
            raise DomainError("PROJECT_OKR_CONTEXT_REQUIRED", 403)
        return value["project_id"]

    return await database.call(read)
