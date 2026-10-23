"""Persist user-managed instructions, command registrations and lazy MCP connections."""

import asyncio
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, SchemaError

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.skill_names import SKILL_ALIASES
from roami_agent.protocol.tools import Tool
from roami_agent.server.model_settings import ModelSettings
from roami_agent.server.skill_package import materialize_package, package_files
from roami_agent.tools.mcp import Connection, validate_servers

NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
KINDS = {"skills", "cli", "mcp"}
MAX_BYTES = 65536


class CapabilityImports:
    def __init__(self, runtime):
        self.runtime = runtime
        self.path = Path(runtime.db.data_root) / "agents" / "capability-imports.json"
        self.lock = asyncio.Lock()
        self.saved = {kind: {} for kind in KINDS}
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size > 1048576
            ):
                raise DomainError("CAPABILITY_IMPORT_PRIVATE_FILE_REQUIRED", 503)
            try:
                saved = json.loads(self.path.read_text())
                if not isinstance(saved, dict) or set(saved) != KINDS:
                    raise ValueError
                for kind, entries in saved.items():
                    if not isinstance(entries, dict) or len(entries) > 64:
                        raise ValueError
                    for name, value in entries.items():
                        if self.validate(kind, value)["name"] != name:
                            raise ValueError
                self.check_collisions(saved)
            except (ValueError, OSError, DomainError):
                raise DomainError("CAPABILITY_IMPORT_INVALID", 503) from None
            self.saved = saved
        for kind, entries in self.saved.items():
            for value in entries.values():
                self.install(kind, value)

    @staticmethod
    def validate(kind, value):
        if kind not in KINDS or not isinstance(value, dict):
            raise DomainError("INVALID_CAPABILITY_IMPORT")
        value = dict(value)
        name = value.get("name")
        if (
            not isinstance(name, str)
            or not NAME.fullmatch(name)
            or (kind == "mcp" and len(name) > 20)
        ):
            raise DomainError("INVALID_CAPABILITY_NAME")
        if len(json.dumps(value, ensure_ascii=False).encode()) > (
            600_000 if kind == "skills" and value.get("files") else MAX_BYTES
        ):
            raise DomainError("CAPABILITY_IMPORT_TOO_LARGE", 413)
        if kind == "skills":
            if set(value) - {"name", "description", "text", "files", "origin"}:
                raise DomainError("INVALID_CAPABILITY_IMPORT")
            package_files(value)
            if (
                not isinstance(value.get("text"), str)
                or not value["text"].strip()
                or len(value["text"].encode()) > MAX_BYTES
                or not isinstance(value.get("description", ""), str)
                or len(value.get("description", "")) > 2000
            ):
                raise DomainError("INVALID_CAPABILITY_IMPORT")
        elif kind == "cli":
            if set(value) - {
                "name",
                "description",
                "argv",
                "cwd",
                "schema",
                "argumentMode",
                "origin",
            }:
                raise DomainError("INVALID_CAPABILITY_IMPORT")
            if value.get("argumentMode", "json") not in ("json", "argv"):
                raise DomainError("INVALID_CAPABILITY_IMPORT")
            argv = value.get("argv")
            if (
                not isinstance(argv, list)
                or not 1 <= len(argv) <= 100
                or not all(isinstance(arg, str) and "\0" not in arg for arg in argv)
                or not argv[0].strip()
                or "{input}" in argv[0]
                or not isinstance(value.get("description", ""), str)
                or len(value.get("description", "")) > 2000
                or not isinstance(value.get("cwd", ""), str)
                or "\0" in value.get("cwd", "")
            ):
                raise DomainError("INVALID_CAPABILITY_IMPORT")
            schema = value.get("schema", {"type": "object", "properties": {}})
            try:
                if not isinstance(schema, dict) or schema.get("type") != "object":
                    raise ValueError
                validate_schema_refs(schema)
                Draft202012Validator.check_schema(schema)
            except (SchemaError, ValueError):
                raise DomainError("INVALID_CAPABILITY_SCHEMA") from None
            value["schema"] = schema
        else:
            if set(value) - {"name", "config", "origin"} or not isinstance(
                value.get("config"), dict
            ):
                raise DomainError("INVALID_MCP_CONFIG")
            config = dict(value["config"])
            if set(config) - {
                "transport",
                "type",
                "command",
                "args",
                "url",
                "cwd",
                "env_env",
                "header_env",
                "key_env",
                "read_only",
                "timeout_seconds",
            }:
                raise DomainError("INVALID_MCP_CONFIG")
            transport = config.pop("type", None)
            if transport is not None and not isinstance(transport, str):
                raise DomainError("INVALID_MCP_CONFIG")
            config.setdefault(
                "transport",
                ("streamable_http" if transport == "http" else transport)
                or ("streamable_http" if config.get("url") else "stdio"),
            )
            if transport not in {None, "http", "stdio", "sse", "streamable_http"} or (
                transport
                and config["transport"] != ("streamable_http" if transport == "http" else transport)
            ):
                raise DomainError("INVALID_MCP_CONFIG")
            if "cwd" in config and (not isinstance(config["cwd"], str) or "\0" in config["cwd"]):
                raise DomainError("INVALID_MCP_CONFIG")
            if any(
                key in config and not isinstance(config[key], str) for key in ("command", "url")
            ):
                raise DomainError("INVALID_MCP_CONFIG")
            if "args" in config and (
                not isinstance(config["args"], list)
                or not all(isinstance(arg, str) for arg in config["args"])
            ):
                raise DomainError("INVALID_MCP_CONFIG")
            try:
                validate_servers({name: config})
            except (TypeError, ValueError, AttributeError):
                raise DomainError("INVALID_MCP_CONFIG") from None
            if any("\0" in part for part in [config.get("command", ""), *config.get("args", [])]):
                raise DomainError("INVALID_MCP_CONFIG")
            value["config"] = config
        if "origin" in value and (
            not isinstance(value["origin"], dict)
            or set(value["origin"]) != {"source", "id", "version", "url"}
            or any(
                not isinstance(part, str) or len(part) > 2000 for part in value["origin"].values()
            )
        ):
            raise DomainError("INVALID_CAPABILITY_IMPORT")
        if (
            value.get("origin", {}).get("url")
            and urlsplit(value["origin"]["url"]).scheme != "https"
        ):
            raise DomainError("INVALID_CAPABILITY_IMPORT")
        return value

    def check_collisions(self, entries, replacing=None):
        tools = self.runtime.tools
        for kind, values in entries.items():
            for name in values:
                if replacing == (kind, name):
                    continue
                exists = (
                    (name in tools.skills or name in SKILL_ALIASES)
                    if kind == "skills"
                    else name in self.runtime.mcp.connections
                    if kind == "mcp"
                    else "cli_" + name in tools.registry
                )
                if exists:
                    raise DomainError("CAPABILITY_ALREADY_EXISTS", 409)
        if (
            len(self.runtime.mcp.connections)
            + len(entries.get("mcp", {}))
            - (1 if replacing and replacing[0] == "mcp" else 0)
            > 16
        ):
            raise DomainError("INVALID_MCP_CONFIG")

    def install(self, kind, value):
        name, tools = value["name"], self.runtime.tools
        if kind == "skills":
            references = {}
            for path, raw in package_files(value).items():
                if path == "SKILL.md":
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                references[path] = {"text": text, "version": hashlib.sha256(raw).hexdigest()}
            tools.skills[name] = {
                "text": value["text"],
                "description": value.get("description", ""),
                "version": hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
                "source": "managed",
                "references": references,
                **(
                    {"packagePath": materialize_package(self.runtime.db.data_root, value)}
                    if value.get("files")
                    else {}
                ),
            }
            tools.registry["skill_read"].schema["properties"]["name"]["enum"] = list(tools.skills)
        elif kind == "cli":

            async def invoke(args, binding):
                argv = [
                    part.replace("{input}", json.dumps(args, ensure_ascii=False))
                    for part in value["argv"]
                ]
                if value.get("argumentMode") == "argv":
                    arguments = args.get("args", [])
                    if not isinstance(arguments, list) or not all(
                        isinstance(arg, str) and "\0" not in arg for arg in arguments
                    ):
                        raise DomainError("INVALID_TOOL_ARGUMENTS")
                    argv.extend(arguments)
                payload = {"argv": argv}
                if value.get("cwd"):
                    payload["cwd"] = value["cwd"]
                return await tools.registry["shell"].handler(payload, binding)

            tools.add(
                Tool(
                    "cli_" + name,
                    value.get("description", ""),
                    value["schema"],
                    invoke,
                    effect="write",
                    source="external",
                    main=True,
                    cancellation_stops_execution=True,
                )
            )
        else:
            self.runtime.mcp.connections[name] = Connection(name, value["config"])
            self.runtime.mcp.register_discovery()

    async def uninstall(self, kind, name):
        tools = self.runtime.tools
        if kind == "skills":
            tools.skills.pop(name, None)
            tools.registry["skill_read"].schema["properties"]["name"]["enum"] = list(tools.skills)
        elif kind == "cli":
            tools.registry.pop("cli_" + name, None)
        else:
            connection = self.runtime.mcp.connections.pop(name)
            if connection.task and not connection.task.done():
                connection.task.cancel()
                await asyncio.gather(connection.task, return_exceptions=True)
            self.runtime.mcp._remove(connection)
            self.runtime.mcp.register_discovery()

    def persist(self, saved):
        if len(json.dumps(saved, ensure_ascii=False).encode()) > 1048576:
            raise DomainError("CAPABILITY_IMPORT_TOO_LARGE", 413)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DomainError("CAPABILITY_IMPORT_PRIVATE_FILE_REQUIRED", 503)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".capability-imports-", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w") as output:
                os.fchmod(output.fileno(), 0o600)
                json.dump(saved, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    async def save(self, owner, kind, payload, name=None, remove=False):
        ModelSettings.owner(owner)
        if kind not in KINDS:
            raise DomainError("INVALID_CAPABILITY_IMPORT")
        async with self.lock, self.runtime.capability_settings.lock:
            if name is not None and name not in self.saved[kind]:
                raise DomainError("MANAGED_CAPABILITY_NOT_FOUND", 404)
            if kind == "mcp" and name:
                connection = self.runtime.mcp.connections[name]
                if (
                    connection.current
                    or not connection.queue.empty()
                    or (connection.ready and not connection.ready.done())
                ):
                    raise DomainError("CAPABILITY_BUSY", 409)
            if remove:
                incoming = {}
            elif kind == "mcp" and isinstance(payload, dict) and set(payload) == {"mcpServers"}:
                servers = payload["mcpServers"]
                if not isinstance(servers, dict) or not servers or name:
                    raise DomainError("INVALID_MCP_CONFIG")
                incoming = {
                    key: self.validate(kind, {"name": key, "config": config})
                    for key, config in servers.items()
                }
            else:
                value = self.validate(kind, payload)
                if name is not None and name != value["name"]:
                    raise DomainError("INVALID_CAPABILITY_NAME")
                incoming = {value["name"]: value}
            self.check_collisions({kind: incoming}, (kind, name) if name else None)
            updated = {**self.saved, kind: {**self.saved[kind], **incoming}}
            if remove:
                updated[kind].pop(name)
            if len(updated[kind]) > 64:
                raise DomainError("CAPABILITY_IMPORT_LIMIT", 409)
            for value in incoming.values():
                if kind == "skills":
                    materialize_package(self.runtime.db.data_root, value)
            self.persist(updated)
            if name:
                await self.uninstall(kind, name)
            for value in incoming.values():
                self.install(kind, value)
            self.saved = updated
            self.runtime.capability_settings.apply()
            return self.runtime.capability_settings.view(owner)


def validate_schema_refs(value):
    if isinstance(value, dict):
        for keyword in ("$ref", "$dynamicRef"):
            if keyword in value and not str(value[keyword]).startswith("#"):
                raise ValueError
        for nested in value.values():
            validate_schema_refs(nested)
    elif isinstance(value, list):
        for nested in value:
            validate_schema_refs(nested)
