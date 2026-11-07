import json
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool
from roami_agent.tools.skill_reads import loaded_workflows


class Tools:
    def __init__(self, artifacts=None):
        self.registry: dict[str, Tool] = {}
        self.artifacts = artifacts
        self.disabled_tools: set[str] = set()
        self.shell_disabled_roles: set[str] = set()
        self.disabled_skills: set[str] = set()
        self.skills: dict[str, dict] = {}
        self.directory = None
        self.admission = None
        self.turn_scope = None

    async def binding_scope(self, binding):
        if not self.turn_scope or not binding.get("turnId"):
            return None
        return await self.turn_scope(
            {
                "id": binding["turnId"],
                "owner_id": binding.get("owner"),
                "lease_epoch": binding.get("leaseEpoch"),
            },
            binding.get("role", "main"),
        )

    async def turn_catalog(self, turn, role="main"):
        catalog = self.catalog(role)
        allowed = await self.turn_scope(turn, role) if self.turn_scope else None
        if allowed is None:
            return catalog
        from roami_agent.tools.swarm_coordination_catalog import model_catalog

        return model_catalog(catalog, allowed, foundations=self.directory is not None)

    def add(self, tool):
        if tool.name in self.registry:
            raise DomainError("DUPLICATE_TOOL")
        Draft202012Validator.check_schema(tool.schema)
        if tool.model_schema is not None:
            Draft202012Validator.check_schema(tool.model_schema)
        self.registry[tool.name] = tool

    def optional_skill_metadata(self):
        if not self.directory:
            return []
        return [
            {key: item[key] for key in ("name", "description", "location")}
            for item in self.directory.skill_entries()
            if self.skills[item["name"]].get("source") in {"configured", "managed"}
        ]

    def loaded_workflow_metadata(self, messages):
        if "skill_read" not in self.registry or {"read", "skill_read"} & self.disabled_tools:
            return []
        return loaded_workflows(
            messages,
            {
                name: value
                for name, value in self.skills.items()
                if name not in self.disabled_skills
                and value.get("source") in {"configured", "managed"}
            },
        )

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
            if role == "main" and self.directory and tool.name == "bash":
                wire = deepcopy(wire)
                wire["function"]["description"] = (
                    "Execute registered Roami CLI operations only. Direct shell and host commands "
                    "are unavailable in this role. Use tool_list for the exact command and schema."
                    if role in self.shell_disabled_roles
                    else (
                        "Execute a shell command. The host supplies the working directory and execution context. "
                        "Use registered Roami commands for managed resources."
                    )
                )
            elif role != "main" and self.directory and tool.name == "bash":
                wire = deepcopy(wire)
                if "scope" in wire["function"]["parameters"]["properties"]:
                    wire["function"]["parameters"]["properties"]["scope"]["enum"] = ["workspace"]
            if self.directory and tool.name == "read":
                skills = self.optional_skill_metadata()
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
            tool.validate(args)
        except (ValueError, ValidationError) as exc:
            raise DomainError("INVALID_TOOL_ARGUMENTS") from exc
        if self.directory:
            tool, args = self.directory.resolve(tool, args, role)
            if tool.name in self.disabled_tools:
                raise DomainError("TOOL_DISABLED")
            try:
                tool.validate(args)
            except ValidationError as exc:
                raise DomainError("INVALID_TOOL_ARGUMENTS") from exc
        return tool, args

    async def invoke(self, call, role, binding):
        tool, args = self.validate(call, role)
        binding = dict(binding, role=role)
        if self.admission:
            args, binding = await self.admission(tool, args, binding)
            tool.validate(args)
        value = await tool.handler(args, binding)
        if self.admission and tool.effect == "read":
            await self.admission(tool, args, binding, after=True)
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
