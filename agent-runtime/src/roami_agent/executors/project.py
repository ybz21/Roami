"""New project intents go through the existing authenticated Go project CLI."""

import json
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.tools.process import execute


async def provision_project(settings, task, run):
    target = json.loads(task["intent_json"])["target"]
    if target.get("nodeId", "local") != "local":
        raise DomainError("PROJECT_NODE_UNAVAILABLE")
    if any(target.get(key) for key in ["directory", "projectId", "workspaceId", "base", "remote"]):
        raise DomainError("PROJECT_NEW_TARGET_CONFLICT")
    if target.get("baseDir") and (
        not isinstance(target["baseDir"], str) or not Path(target["baseDir"]).is_absolute()
    ):
        raise DomainError("PROJECT_BASE_DIRECTORY_REQUIRED")
    if target.get("template"):
        raise DomainError("PROJECT_TEMPLATE_NOT_CONFIGURED")
    name = target.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DomainError("PROJECT_NAME_REQUIRED")
    argv = [
        settings.cli_bin,
        "project",
        "create",
        "--name",
        name,
        "--provision-key",
        "project:" + run["launch_id"],
        "--json",
    ]
    if target.get("baseDir"):
        argv.extend(["--base-dir", target["baseDir"]])
    result = await execute(argv, timeout=35, excluded_env=settings.provider_key_environments())
    try:
        payload = json.loads(result["stdout"])
        if not isinstance(payload, dict):
            raise TypeError("invalid project envelope")
        if result["exitCode"]:
            problem = payload.get("error") or {}
            if not isinstance(problem, dict):
                raise TypeError("invalid project error")
            code = problem.get("code", "PROJECT_PROVISION_UNAVAILABLE")
            raise DomainError(
                code
                if isinstance(code, str) and code.startswith("PROJECT_")
                else "PROJECT_PROVISION_UNAVAILABLE"
            )
        entry = payload["data"]
        if (
            not isinstance(entry["key"], str)
            or not entry["key"]
            or not isinstance(entry["dir"], str)
        ):
            raise ValueError("invalid project receipt")
    except (ValueError, KeyError, TypeError) as exc:
        raise DomainError("INVALID_PROJECT_PROVISION_RECEIPT") from exc
    return {"kind": "project", "projectId": entry["key"]}
