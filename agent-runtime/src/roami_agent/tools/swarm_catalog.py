"""Discoverable Main coordination and task-bound member discussion."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema


def register_swarm_tools(registry, swarms):
    async def main(binding, sid):
        info = await swarms.snapshot(binding["owner"], sid)
        if binding.get("taskId") or info["mainConversationId"] != binding["conversation"]:
            raise DomainError("SWARM_MAIN_REQUIRED", 403)
        return info

    async def create(args, binding):
        return await swarms.create(
            binding["owner"],
            {
                **args,
                "mainConversationId": binding["conversation"],
                "commandKey": binding["turnId"] + ":" + binding["toolCallId"],
            },
            binding=binding,
        )

    async def plan(args, binding):
        await main(binding, args["swarmId"])
        return await swarms.plan(
            binding["owner"],
            args["swarmId"],
            {**args, "commandKey": binding["turnId"] + ":" + binding["toolCallId"]},
        )

    async def status(args, binding):
        info = await swarms.snapshot(binding["owner"], args["swarmId"])
        if binding.get("taskId"):
            if not any(item["task_id"] == binding["taskId"] for item in info["work"]):
                raise DomainError("SWARM_MEMBER_REQUIRED", 403)
        elif info["mainConversationId"] != binding["conversation"]:
            raise DomainError("SWARM_MAIN_REQUIRED", 403)
        return info

    async def post(args, binding):
        return await swarms.post(
            binding["owner"],
            args["swarmId"],
            {"text": args["text"], "commandKey": binding["turnId"] + ":" + binding["toolCallId"]},
            binding=binding,
        )

    async def control(args, binding):
        await main(binding, args["swarmId"])
        return await swarms.control(
            binding["owner"],
            args["swarmId"],
            {**args, "commandKey": binding["turnId"] + ":" + binding["toolCallId"]},
        )

    async def dependencies(args, binding):
        await main(binding, args["swarmId"])
        return await swarms.dependencies(
            binding["owner"],
            args["swarmId"],
            {**args, "commandKey": binding["turnId"] + ":" + binding["toolCallId"]},
        )

    string = {"type": "string", "minLength": 1}
    dep = object_schema(
        {"member": string, "revision": {"type": "integer", "minimum": 1}, "artifactId": string},
        ["member"],
    )
    item = object_schema(
        {
            "member": string,
            "executor": {"type": "string", "enum": ["native", "codex", "claude", "opencode", "pi"]},
            "title": string,
            "goal": string,
            "acceptance": string,
            "integration": {"type": "boolean"},
            "dependencies": {"type": "array", "items": dep},
        },
        ["member", "executor", "title", "goal", "acceptance"],
    )
    for name, description, schema, call, is_main, effect in [
        (
            "swarm_dependencies",
            "Update a work item's required upstream revisions after confirmed stopping, or retry a known failed dispatch. Never replace a task or executor; resume existing work through task_steer after rebinding verified dependencies. Rejects cycles and unknown/still-running attempts.",
            object_schema(
                {
                    "swarmId": string,
                    "expectedRevision": {"type": "integer", "minimum": 1},
                    "workId": string,
                    "dependencies": {"type": "array", "items": dep},
                },
                ["swarmId", "expectedRevision", "workId", "dependencies"],
            ),
            dependencies,
            True,
            "write",
        ),
        (
            "swarm_create",
            "Create a collaborative swarm bound to this existing Main conversation. No separate commander. Discover swarm_plan to assign managed tasks.",
            object_schema(
                {"name": string, "goal": string, "target": {"type": "object"}}, ["name", "goal"]
            ),
            create,
            True,
            "write",
        ),
        (
            "swarm_plan",
            "Append named members/work items to the current swarm plan at expectedRevision. Select appropriate executors (native means Roami Worker), explicit goals and acceptance; integration=true is a final integration task that depends on all other items. Hard dependencies dispatch only after verified matching revisions. Do not redelegate existing work: use task_steer for changes, preserve its executor and workspace. Unknown launches never retry as new tasks.",
            object_schema(
                {
                    "swarmId": string,
                    "expectedRevision": {"type": "integer", "minimum": 1},
                    "items": {"type": "array", "minItems": 1, "maxItems": 100, "items": item},
                },
                ["swarmId", "expectedRevision", "items"],
            ),
            plan,
            True,
            "write",
        ),
        (
            "swarm_status",
            "Read your swarm group chat, work items, dependencies and authoritative task state; reports are not verification. Main may inspect only its bound conversation; workers only their own group.",
            object_schema({"swarmId": string}, ["swarmId"]),
            status,
            True,
            "read",
        ),
        (
            "swarm_post",
            "Post a coordination question or progress note to your swarm group chat. Author is bound to Main or the current managed member/run. Does not mark tasks complete or send terminal input.",
            object_schema({"swarmId": string, "text": string}, ["swarmId", "text"]),
            post,
            True,
            "write",
        ),
        (
            "swarm_control",
            "Pause/resume new dispatches, stop managed tasks with existing cancellation, or archive without closing member sessions. No automatic resource cleanup.",
            object_schema(
                {
                    "swarmId": string,
                    "expectedRevision": {"type": "integer", "minimum": 1},
                    "action": {"type": "string", "enum": ["pause", "resume", "stop", "archive"]},
                },
                ["swarmId", "expectedRevision", "action"],
            ),
            control,
            True,
            "write",
        ),
    ]:
        registry.add(Tool(name, description, schema, call, main=is_main, effect=effect))
