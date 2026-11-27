"""Project team memory and verified project guidance over an existing Swarm."""

import json
import re

from roami_agent.protocol.errors import DomainError, public_error_code
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.swarm_memory import digest
from roami_agent.storage.swarm_repository import changed, group
from roami_agent.storage.swarm_scopes import require_scope
from roami_agent.tools.process import execute


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


def guidance_skill_kind(name, path):
    if not isinstance(name, str):
        return None
    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", name) and path == f"skills/{name}/SKILL.md":
        return "project"
    connector = re.fullmatch(r"connector-([a-zA-Z][a-zA-Z0-9_-]{0,63})", name)
    if connector and path == f"connectors/{connector[1]}/SKILL.md":
        return "connector"
    return None


def from_project(workspace):
    files = workspace["projectFiles"]
    content, sha = files.get("teamMemory", ""), files.get("teamMemorySha256")
    if not isinstance(content, str) or not isinstance(sha, str) or digest(content) != sha:
        raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
    result = {
        "content": content,
        "sha256": sha,
        "source": ".roami/okr/memory/team.md",
        "sizeBytes": len(content.encode()),
        "limitBytes": 65536,
        "available": True,
    }
    if files.get("operationReceiptsSupported") is True:
        result["operationReceiptsSupported"] = True
    receipt = files.get("operationReceipt")
    if receipt is not None:
        if (
            not isinstance(receipt, dict)
            or receipt.get("kind") != "memory_append"
            or not isinstance(receipt.get("key"), str)
            or not receipt["key"]
            or any(
                not isinstance(receipt.get(k), str) or not re.fullmatch(r"[0-9a-f]{64}", receipt[k])
                for k in ("requestSha256", "previousSha256", "resultSha256")
            )
            or not isinstance(receipt.get("recordedAt"), str)
            or not receipt["recordedAt"]
        ):
            raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
        result["operationReceipt"] = receipt
    instructions = files.get("mainInstructions", "")
    workflow = files.get("workflow", "")
    skills = files.get("skills", [])
    if (
        not isinstance(instructions, str)
        or len(instructions.encode()) > 65536
        or not isinstance(workflow, str)
        or len(workflow.encode()) > 65536
        or not isinstance(skills, list)
        or len(skills) > 48
    ):
        raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
    total, seen = 0, set()
    counts = {"project": 0, "connector": 0}
    for skill in skills:
        if not isinstance(skill, dict):
            raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
        name, content = skill.get("id"), skill.get("content")
        kind = guidance_skill_kind(name, skill.get("path"))
        if (
            kind is None
            or name in seen
            or not isinstance(content, str)
            or not content
            or digest(content) != skill.get("sha256")
        ):
            raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
        counts[kind] += 1
        if counts[kind] > (16 if kind == "project" else 32):
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


def project_guidance_references(memory):
    guidance = memory.get("projectGuidance")
    if not guidance:
        return memory
    return {
        **memory,
        "projectGuidance": {
            **{key: guidance[key] for key in ("source", "instructions", "workflowSource", "scope")},
            "workflowSha256": digest(guidance["workflow"]),
            "skills": [
                {key: skill[key] for key in ("id", "path", "sha256")}
                for skill in guidance["skills"]
            ],
            "loadPolicy": (
                "Read the current project workflow and the relevant declared Skills before acting. "
                "Paths are relative to .roami/okr/. Use the selected native project's files or "
                "swarm_project_context. Recheck confirmed project guidance when a file differs."
            ),
        },
    }


class ProjectSwarmMemory:
    @staticmethod
    async def read(swarms, owner, sid):
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

    @staticmethod
    async def write(swarms, owner, sid, spec):
        workspace = await project_context(swarms, owner, sid, memory=spec)
        if workspace is not None:
            result = from_project(workspace)
            if spec.get("operationKey") and (
                spec.get("mode") != "append"
                or (result.get("operationReceipt") or {}).get("key") != spec["operationKey"]
            ):
                raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
            await swarms.db.call(
                lambda db: changed(db, group(db, owner, sid), "swarm.memory_changed"), write=True
            )
            return result

    references = staticmethod(project_guidance_references)
