"""Node-local capability switches; catalogs and execution share the same policy."""

import asyncio
import json
import os
import stat
import tempfile
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.server.model_settings import ModelSettings


class CapabilitySettings:
    def __init__(self, runtime):
        self.runtime = runtime
        self.path = Path(runtime.db.data_root) / "agents" / "capability-settings.json"
        self.lock = asyncio.Lock()
        self.saved = {"tools": [], "skills": []}
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size > 64000
            ):
                raise DomainError("CAPABILITY_SETTINGS_PRIVATE_FILE_REQUIRED", 503)
            try:
                self.saved = json.loads(self.path.read_text())
            except (ValueError, OSError):
                raise DomainError("CAPABILITY_SETTINGS_INVALID", 503) from None
            if (
                not isinstance(self.saved, dict)
                or set(self.saved) != {"tools", "skills"}
                or any(
                    not isinstance(value, list)
                    or len(value) > 1000
                    or any(
                        not isinstance(name, str) or not name or len(name) > 300 for name in value
                    )
                    for value in self.saved.values()
                )
            ):
                raise DomainError("CAPABILITY_SETTINGS_INVALID", 503)
        self.apply()

    def apply(self):
        self.runtime.tools.disabled_tools = set(self.saved["tools"])
        self.runtime.tools.disabled_skills = set(self.saved["skills"])

    def view(self, owner):
        ModelSettings.owner(owner)
        tools = self.runtime.tools
        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "schema": tool.schema,
                    "effect": tool.effect,
                    "main": tool.main,
                    "enabled": tool.name not in tools.disabled_tools,
                }
                for tool in sorted(tools.registry.values(), key=lambda tool: tool.name)
            ],
            "skills": [
                {"name": name, **value, "enabled": name not in tools.disabled_skills}
                for name, value in sorted(tools.skills.items())
            ],
            "mcp": [
                {
                    "name": name,
                    "transport": connection.config.get("transport", "stdio"),
                    "state": "connected"
                    if connection.session
                    else "unavailable"
                    if connection.failures
                    else "not_connected",
                    "tools": len(connection.names),
                }
                for name, connection in sorted(self.runtime.mcp.connections.items())
            ],
        }

    async def save(self, owner, patch):
        ModelSettings.owner(owner)
        if (
            not isinstance(patch, dict)
            or set(patch) != {"kind", "name", "enabled"}
            or not isinstance(patch["kind"], str)
            or patch["kind"] not in {"tools", "skills"}
            or not isinstance(patch["name"], str)
            or type(patch["enabled"]) is not bool
        ):
            raise DomainError("INVALID_CAPABILITY_CONFIG")
        async with self.lock:
            names = (
                self.runtime.tools.registry
                if patch["kind"] == "tools"
                else self.runtime.tools.skills
            )
            if patch["name"] not in names:
                raise DomainError("CAPABILITY_NOT_FOUND", 404)
            disabled = set(self.saved[patch["kind"]])
            if patch["enabled"]:
                disabled.discard(patch["name"])
            else:
                disabled.add(patch["name"])
            if len(disabled) > 1000:
                raise DomainError("INVALID_CAPABILITY_CONFIG")
            saved = {**self.saved, patch["kind"]: sorted(disabled)}
            if len(json.dumps(saved).encode()) > 64000:
                raise DomainError("INVALID_CAPABILITY_CONFIG")
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            info = self.path.parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("CAPABILITY_SETTINGS_PRIVATE_FILE_REQUIRED", 503)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".capability-settings-", dir=self.path.parent
            )
            try:
                with os.fdopen(descriptor, "w") as output:
                    os.fchmod(output.fileno(), 0o600)
                    json.dump(saved, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.saved = saved
            self.apply()
            return self.view(owner)
