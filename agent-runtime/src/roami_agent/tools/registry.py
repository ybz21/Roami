import json
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tool_arguments import validate_tool_arguments
from roami_agent.protocol.tools import Tool


class Tools:
    def __init__(self, artifacts=None):
        self.registry: dict[str, Tool] = {}
        self.artifacts = artifacts
        self.disabled_tools: set[str] = set()
        self.disabled_skills: set[str] = set()
        self.skills: dict[str, dict] = {}
        self.directory = None

    def add(self, tool):
        if tool.name in self.registry:
            raise DomainError("DUPLICATE_TOOL")
        Draft202012Validator.check_schema(tool.schema)
        self.registry[tool.name] = tool

    def catalog(self, role="main"):
        result = []
        for tool in self.registry.values():
            if self.directory:
                from roami_agent.tools.foundations import (
                    FOUNDATIONS,
                    WORKER_FOUNDATIONS,
                )

                names = FOUNDATIONS if role == "main" else WORKER_FOUNDATIONS
                if tool.name not in names:
                    continue
            if tool.name in self.disabled_tools or role == "main" and not tool.main:
                continue
            wire = tool.wire()
            if role == "main" and self.directory and tool.name == "delegate":
                wire = deepcopy(wire)
                wire["function"]["parameters"]["required"] = ["goal", "routing", "requestComplete"]
                wire["function"]["parameters"]["properties"].pop("executor", None)
            if role == "main" and self.directory and tool.name == "bash":
                wire = deepcopy(wire)
                wire["function"]["description"] = (
                    "Execute discovered Roami CLI operations. Main has no implicit shell workspace. "
                    "For user-authorized local machine operations, set scope=host and omit cwd; "
                    "host scope is general execution in a temporary working directory, not a read-only sandbox. "
                    "For project code or file deliverables, keep workspace scope and delegate to a worker "
                    "with the user-selected directory, or an automatic private directory for new native work. "
                    "Registered permissions and execution receipts remain enforced."
                )
            elif role != "main" and self.directory and tool.name == "bash":
                wire = deepcopy(wire)
                if "scope" in wire["function"]["parameters"]["properties"]:
                    wire["function"]["parameters"]["properties"]["scope"]["enum"] = ["workspace"]
            if self.directory and tool.name == "read":
                skills = [
                    {key: item[key] for key in ("name", "description", "location")}
                    for item in self.directory.skill_entries()
                    if self.skills[item["name"]].get("source") in {"configured", "managed"}
                ]
                if skills:
                    wire = deepcopy(wire)
                    wire["function"]["description"] += (
                        "\nAvailable optional Skills (metadata only): "
                        + encoded(skills)
                        + ". Read the relevant Skill's instructions before using its workflow."
                    )
            result.append(wire)
        return result

    def validate(self, call, role):
        name = call["function"]["name"]
        tool = self.registry.get(name)
        if name in self.disabled_tools:
            raise DomainError("TOOL_DISABLED")
        if self.directory:
            from roami_agent.tools.foundations import FOUNDATIONS

            parent = {
                "skill_read": "read",
                "file_read": "read",
                "file_patch": "edit",
                "file_write": "write",
                "web_research": "delegate",
            }.get(name, "bash" if name not in FOUNDATIONS else name)
            if parent in self.disabled_tools:
                raise DomainError("TOOL_DISABLED")
        if not tool or (role == "main" and not tool.main):
            raise DomainError("TOOL_UNAVAILABLE")
        try:
            args = json.loads(call["function"]["arguments"])
            validate_tool_arguments(tool.schema, args)
        except (ValueError, ValidationError) as exc:
            raise DomainError("INVALID_TOOL_ARGUMENTS") from exc
        if self.directory:
            tool, args = self.directory.resolve(tool, args, role)
            if tool.name in self.disabled_tools:
                raise DomainError("TOOL_DISABLED")
            try:
                validate_tool_arguments(tool.schema, args)
            except ValidationError as exc:
                raise DomainError("INVALID_TOOL_ARGUMENTS") from exc
        return tool, args

    async def invoke(self, call, role, binding):
        tool, args = self.validate(call, role)
        value = await tool.handler(args, dict(binding, role=role))
        body = encoded(value).encode()
        # Status lists must survive the gateway's provenance recheck before commit.
        if (
            len(body) <= 128_000
            or self.artifacts is None
            or tool.name in {"task_status", "task_reply", "task_queue_reply", "reply"}
        ):
            return value
        reference = await self.artifacts.put(
            binding["owner"],
            body,
            mime_type="application/json",
            name="tool-result.json",
            task_id=binding.get("taskId"),
            message_id=binding.get("assistantMessageId"),
            metadata={"source": "tool_result", "toolName": tool.name},
        )
        essential = {
            key: item
            for key, item in (value.items() if isinstance(value, dict) else ())
            if key
            in {
                "exitCode",
                "state",
                "error",
                "acceptedOnly",
                "requestComplete",
                "kind",
                "taskId",
                "id",
            }
            and isinstance(item, (bool, int, float, str, type(None)))
            and len(encoded(item)) <= 1000
        }
        return {
            **essential,
            "preview": body[:4000].decode(errors="ignore"),
            "artifactRefs": [reference],
            "outputExternalized": True,
        }
