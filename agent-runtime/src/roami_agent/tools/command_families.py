"""Public command families over role-bound internal operations."""

import json
import re
from pathlib import Path

from roami_agent.protocol.errors import DomainError

COMMANDS = json.loads((Path(__file__).resolve().parents[1] / "commands.json").read_text())
INTERNAL = {"artifact_read", "capability_overview"}


def option_name(field):
    return "--" + re.sub(r"[A-Z]", lambda match: "-" + match[0].lower(), field)


def command_argv(path, schema):
    prefix = ["roami", *path]
    argv = list(prefix)
    for field in schema.get("required", []):
        spec = schema.get("properties", {}).get(field, {})
        if spec.get("type") not in {"string", "integer", "number", "boolean"}:
            return [*prefix, "--input", "JSON"]
        argv.extend([option_name(field), field])
    return argv


def command_arguments(rest, schema):
    if rest and (rest[0] == "--input" or rest[0].startswith("--input=")):
        if rest[0] == "--input" and len(rest) == 2:
            raw = rest[1]
        elif len(rest) == 1 and rest[0].startswith("--input="):
            raw = rest[0].partition("=")[2]
        else:
            raise DomainError("INVALID_CLI_ARGUMENTS")
        try:
            args = json.loads(raw)
        except (ValueError, TypeError):
            raise DomainError("INVALID_CLI_ARGUMENTS") from None
        if not isinstance(args, dict):
            raise DomainError("INVALID_CLI_ARGUMENTS")
        return args
    options = {
        option_name(field): (field, spec.get("type"))
        for field, spec in schema.get("properties", {}).items()
    }
    args, rest = {}, list(rest)
    while rest:
        flag, equals, value = rest.pop(0).partition("=")
        if flag not in options:
            raise DomainError("INVALID_CLI_ARGUMENTS")
        field, kind = options[flag]
        if field in args or kind not in {"string", "integer", "number", "boolean"}:
            raise DomainError("INVALID_CLI_ARGUMENTS")
        if not equals:
            if kind == "boolean" and (not rest or rest[0].startswith("--")):
                args[field] = True
                continue
            if not rest:
                raise DomainError("INVALID_CLI_ARGUMENTS")
            value = rest.pop(0)
        if kind == "string":
            args[field] = value
        else:
            try:
                args[field] = json.loads(value)
            except ValueError:
                raise DomainError("INVALID_CLI_ARGUMENTS") from None
    return args


def public_operation(argv, schemas):
    for name, path in COMMANDS.items():
        if argv[: len(path)] == path:
            return name, command_arguments(argv[len(path) :], schemas.get(name, {}))
    if argv[:1] in (["chrome"], ["adb"]):
        raise DomainError("TOOL_UNAVAILABLE")
    return None


def operation_kind(tool):
    if tool.name.startswith("mcp_"):
        return "mcp"
    if tool.name.startswith("computer_") or tool.name.startswith("http_"):
        return "tool"
    return "cli"
