"""Public command families over role-bound internal operations."""

import json
import re
from pathlib import Path

from roami_agent.protocol.errors import DomainError

COMMANDS = json.loads((Path(__file__).resolve().parents[1] / "commands.json").read_text())
INTERNAL = {"artifact_read", "capability_overview"}


def chrome_operation(argv):
    if not argv:
        raise DomainError("INVALID_CLI_ARGUMENTS")
    verb, rest = argv[0], list(argv[1:])
    flags = {}
    positionals = []
    while rest:
        value = rest.pop(0)
        if value.startswith("--"):
            if (
                value not in {"--resource", "--observation", "--target"}
                or value in flags
                or not rest
            ):
                raise DomainError("INVALID_CLI_ARGUMENTS")
            flags[value] = rest.pop(0)
        else:
            positionals.append(value)
    if verb == "new" and len(positionals) <= 1 and not flags:
        return "browser_open", {"url": positionals[0]} if positionals else {}
    if verb == "observe" and not positionals and set(flags) == {"--target"}:
        return "browser_open", {"targetId": flags["--target"]}
    if verb in {"observe", "screenshot"} and not positionals and set(flags) == {"--resource"}:
        return "browser_observe", {"resourceId": flags["--resource"]}
    if verb in {"observe", "screenshot"} and not positionals and not flags:
        return "browser_observe", {}
    if set(flags) not in (set(), {"--observation"}, {"--resource"}):
        raise DomainError("INVALID_CLI_ARGUMENTS")
    args = {"kind": verb}
    if "--observation" in flags:
        args["observationId"] = flags["--observation"]
    if "--resource" in flags:
        args["resourceId"] = flags["--resource"]
    if verb == "goto" and len(positionals) == 1:
        args["url"] = positionals[0]
    elif verb == "click" and len(positionals) == 1:
        args["selector"] = positionals[0]
    elif verb in {"fill", "type"} and len(positionals) == 2:
        args.update(selector=positionals[0], text=positionals[1])
    elif verb == "upload" and len(positionals) == 2:
        args.update(selector=positionals[0], path=positionals[1])
    elif verb == "press" and len(positionals) == 1:
        args["key"] = positionals[0]
    else:
        raise DomainError("INVALID_CLI_ARGUMENTS")
    return "browser_act", args


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
    if argv[:1] == ["chrome"]:
        return chrome_operation(argv[1:])
    return None


def operation_kind(tool):
    if tool.name.startswith("mcp_"):
        return "mcp"
    if tool.name.startswith("computer_") or tool.name.startswith("http_"):
        return "tool"
    return "cli"
