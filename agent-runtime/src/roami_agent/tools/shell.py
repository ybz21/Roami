"""Shell argv execution within the trusted task workspace or configured roots."""

from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.process import execute


def register_shell(registry, settings):
    async def shell(args, binding):
        workspace = binding.get("workspace")
        if binding.get("taskId") and not workspace:
            raise DomainError("TASK_WORKSPACE_REQUIRED")
        directory = args.get("cwd") or (workspace or {}).get("directory")
        if not directory:
            raise DomainError("WORKSPACE_REQUIRED")
        cwd = Path(directory).expanduser()
        if workspace and not cwd.is_absolute():
            cwd = Path(workspace["directory"]) / cwd
        cwd = cwd.resolve()
        roots = [Path(workspace["directory"]).resolve()] if workspace else settings.shell_roots
        if not any(cwd == root or root in cwd.parents for root in roots):
            raise DomainError("WORKSPACE_OUTSIDE_CONFIGURED_ROOTS")
        return await execute(args["argv"], cwd=cwd, timeout=min(args.get("timeout", 60), 60))

    registry.add(
        Tool(
            "shell",
            "Execute an argv in the prepared task workspace (default cwd) or configured roots; no implicit shell.",
            object_schema(
                {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 100,
                    },
                    "cwd": {"type": "string"},
                    "timeout": {"type": "integer", "minimum": 1, "maximum": 60},
                },
                ["argv"],
            ),
            shell,
            effect="write",
            cancellation_stops_execution=True,
        )
    )
