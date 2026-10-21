"""Public command families over role-bound internal operations."""

import json
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
    if set(flags) != {"--observation"}:
        raise DomainError("INVALID_CLI_ARGUMENTS")
    args = {"observationId": flags["--observation"], "kind": verb}
    if verb == "goto" and len(positionals) == 1:
        args["url"] = positionals[0]
    elif verb == "click" and len(positionals) == 1:
        args["selector"] = positionals[0]
    elif verb in {"fill", "type"} and len(positionals) == 2:
        args.update(selector=positionals[0], text=positionals[1])
    elif verb == "press" and len(positionals) == 1:
        args["key"] = positionals[0]
    else:
        raise DomainError("INVALID_CLI_ARGUMENTS")
    return "browser_act", args


def public_operation(argv):
    for name, path in COMMANDS.items():
        if argv[: len(path)] == path and argv[len(path) : len(path) + 1] == ["--input"]:
            if len(argv) != len(path) + 2:
                raise DomainError("INVALID_CLI_ARGUMENTS")
            try:
                args = json.loads(argv[-1])
            except (ValueError, TypeError):
                raise DomainError("INVALID_CLI_ARGUMENTS") from None
            if not isinstance(args, dict):
                raise DomainError("INVALID_CLI_ARGUMENTS")
            return name, args
    if argv[:1] == ["chrome"]:
        return chrome_operation(argv[1:])
    return None


def operation_kind(tool):
    if tool.name.startswith("mcp_"):
        return "mcp"
    if tool.name.startswith("computer_") or tool.name.startswith("http_"):
        return "tool"
    return "cli"
