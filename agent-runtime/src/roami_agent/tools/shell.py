"""Shell argv execution within the trusted task workspace or configured roots."""

import codecs
from pathlib import Path
from tempfile import TemporaryDirectory

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.process import execute


def register_shell(registry, settings, artifacts=None):
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
        if not artifacts:
            return await execute(
                args["argv"],
                cwd=cwd,
                timeout=args.get("timeout") or None,
                excluded_env=settings.provider_key_environments(),
            )
        with TemporaryDirectory(prefix=".shell-output-", dir=artifacts.data_root) as directory:
            result = await execute(
                args["argv"],
                cwd=cwd,
                timeout=args.get("timeout") or None,
                excluded_env=settings.provider_key_environments(),
                output_directory=directory,
            )
            references = []
            for stream in ["stdout", "stderr"]:
                path = result[stream]
                size = path.stat().st_size
                with path.open("rb") as file:
                    preview = file.read(16000)
                try:
                    text = codecs.getincrementaldecoder("utf-8")().decode(
                        preview, final=size <= 16000
                    )
                    binary = "\0" in text
                except UnicodeDecodeError:
                    text, binary = "", True
                if size > 16000 or binary:
                    try:
                        reference = await artifacts.put_file(
                            binding["owner"],
                            path,
                            mime_type="application/octet-stream" if binary else "text/plain",
                            name="shell-" + stream + (".bin" if binary else ".txt"),
                            task_id=binding.get("taskId"),
                            message_id=binding.get("assistantMessageId"),
                            metadata={"source": "shell", "stream": stream},
                        )
                    except (DomainError, OSError):
                        raise DomainError("TOOL_OUTCOME_UNKNOWN") from None
                    references.append(reference)
                    text = "" if binary else preview[:4000].decode(errors="ignore")
                result[stream] = text
            if references:
                result.update(artifactRefs=references, outputExternalized=True)
            return result

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
                    },
                    "cwd": {"type": "string"},
                    "timeout": {"type": "integer", "minimum": 0},
                },
                ["argv"],
            ),
            shell,
            effect="write",
            cancellation_stops_execution=True,
        )
    )
