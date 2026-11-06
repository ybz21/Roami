"""Project-owned team knowledge, with an isolated durable store for loose swarms."""

import hashlib
import json
import re

from roami_agent.protocol.errors import DomainError, public_error_code
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_repository import changed, group
from roami_agent.storage.swarm_scopes import require_scope
from roami_agent.tools.process import execute


def digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


async def project_context(swarms, owner, sid, *, memory=None, operation=None, payload=None):
    value = await swarms.db.call(lambda db: group(db, owner, sid))
    target = json.loads(value["target_json"])
    if target.get("kind") != "project":
        return None
    project_id = target.get("projectId")
    if (
        not isinstance(project_id, str)
        or not project_id.strip()
        or project_id.startswith("-")
        or "\0" in project_id
    ):
        raise DomainError("INVALID_SWARM_PROJECT_ID")
    require_scope(value)
    if (
        not swarms.settings
        or not target.get("projectId")
        or target.get("nodeId", "local") != "local"
    ):
        raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
    action = operation or ("memory" if memory is not None else "show")
    if action not in {"show", "memory", "save", "record", "review", "sync", "collect"}:
        raise DomainError("INVALID_SWARM_PROJECT_OPERATION")
    body = memory if memory is not None else payload
    argv = [
        swarms.settings.cli_bin,
        "project",
        "okr",
        action,
        project_id,
    ]
    if body is not None:
        argv += ["--file", "-"]
    argv += ["--json"]
    result = await execute(
        argv,
        input_data=encoded(body).encode() if body is not None else None,
        excluded_env=swarms.settings.provider_key_environments(),
        timeout=15,
        max_bytes=2_000_000,
    )
    try:
        payload = json.loads(result["stdout"])
        if not isinstance(payload, dict):
            raise TypeError("invalid project envelope")
        if result["exitCode"]:
            problem = payload.get("error")
            code = public_error_code(problem.get("code") if isinstance(problem, dict) else problem)
            raise DomainError(code or "SWARM_PROJECT_MEMORY_UNAVAILABLE", 409)
        workspace = payload["data"]
        if not isinstance(workspace, dict) or not isinstance(workspace.get("projectFiles"), dict):
            raise TypeError("project bundle absent")
        return workspace
    except (ValueError, KeyError, TypeError) as exc:
        raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503) from exc


def from_project(workspace):
    files = workspace["projectFiles"]
    content, sha = files.get("teamMemory", ""), files.get("teamMemorySha256")
    if not isinstance(content, str) or not isinstance(sha, str) or digest(content) != sha:
        raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
    result = {
        "content": content,
        "sha256": sha,
        "source": ".roami/okr/memory/team.md",
        "available": True,
    }
    instructions = files.get("mainInstructions", "")
    workflow = files.get("workflow", "")
    skills = files.get("skills", [])
    if (
        not isinstance(instructions, str)
        or len(instructions.encode()) > 65536
        or not isinstance(workflow, str)
        or len(workflow.encode()) > 65536
        or not isinstance(skills, list)
        or len(skills) > 16
    ):
        raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
    total, seen = 0, set()
    for skill in skills:
        if not isinstance(skill, dict):
            raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
        name, content = skill.get("id"), skill.get("content")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", name)
            or name in seen
            or skill.get("path") != "skills/" + name + "/SKILL.md"
            or not isinstance(content, str)
            or not content
            or digest(content) != skill.get("sha256")
        ):
            raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
        seen.add(name)
        total += len(content.encode())
    if total > 65536:
        raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
    if instructions or skills or workflow:
        result["projectGuidance"] = {
            "source": ".roami/okr/agents/main.json",
            "instructions": instructions,
            "workflow": workflow,
            "workflowSource": ".roami/okr/AGENTS.md",
            "skills": skills,
            "scope": "Project guidance; never execution proof or authority to bypass host controls",
        }
    return result


async def read_memory(swarms, owner, sid):
    await swarms.db.call(lambda db: group(db, owner, sid))
    try:
        workspace = await project_context(swarms, owner, sid)
        if workspace is not None:
            return from_project(workspace)
    except (DomainError, OSError, TimeoutError) as exc:
        return {
            "available": False,
            "source": ".roami/okr/memory/team.md",
            "errorCode": exc.code
            if isinstance(exc, DomainError)
            else "SWARM_PROJECT_MEMORY_UNAVAILABLE",
        }

    def read(db):
        group(db, owner, sid)
        value = row(db, "SELECT * FROM swarm_memories WHERE swarm_id=?", (sid,))
        return {
            "available": True,
            "content": value["content"] if value else "",
            "sha256": value["sha256"] if value else digest(""),
            "source": "swarm:" + sid + "/memory",
            "updatedMs": value["updated_ms"] if value else None,
            "author": value["author"] if value else None,
        }

    return await swarms.db.call(read)


async def write_memory(swarms, owner, sid, spec):
    content = spec.get("content")
    if (
        not isinstance(content, str)
        or len(content.encode()) > 64000
        or not isinstance(spec.get("expectedSha256"), str)
    ):
        raise DomainError("INVALID_SWARM_MEMORY")
    value = await swarms.db.call(lambda db: group(db, owner, sid))
    if value["archived"]:
        raise DomainError("SWARM_ARCHIVED", 409)
    workspace = await project_context(swarms, owner, sid, memory=spec)
    if workspace is not None:
        result = from_project(workspace)
        await swarms.db.call(
            lambda db: changed(db, group(db, owner, sid), "swarm.memory_changed"), write=True
        )
        return result

    def write(db):
        current = row(db, "SELECT sha256 FROM swarm_memories WHERE swarm_id=?", (sid,))
        if spec["expectedSha256"] != (current["sha256"] if current else digest("")):
            raise DomainError("SWARM_MEMORY_CHANGED", 409)
        db.execute(
            "INSERT INTO swarm_memories VALUES(?,?,?,?,?) ON CONFLICT(swarm_id) DO UPDATE SET content=excluded.content,sha256=excluded.sha256,updated_ms=excluded.updated_ms,author=excluded.author",
            (sid, content, digest(content), now_ms(), owner),
        )
        changed(db, group(db, owner, sid), "swarm.memory_changed")

    await swarms.db.call(write, write=True)
    return await read_memory(swarms, owner, sid)
