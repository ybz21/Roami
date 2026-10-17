"""Short Main tools bound to conversation-scoped application services."""

from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool, object_schema


def register_main_tools(registry, tasks, memory):
    async def delegate(args, binding):
        return await tasks.create(
            binding["owner"],
            binding["conversation"],
            args["goal"],
            key=binding["toolCallId"],
            parent_task_id=binding.get("taskId"),
            executor=args.get("executor", "native"),
            target=args.get("target"),
            from_message_id=args.get("fromMessageId"),
            origin_message_id=binding["originMessageId"],
        )

    async def status(args, binding):
        return await tasks.list(binding["owner"], binding["conversation"])

    async def recall(args, binding):
        hits = await memory.search(
            binding["owner"],
            args["query"],
            conversation_id=binding["conversation"]
            if args.get("scope", "conversation") == "conversation"
            else None,
            project_id=args.get("projectId"),
            limit=8,
        )
        result, remaining = [], 6000
        for hit in hits:
            excerpt = hit["body"][:500]
            item = {
                "id": hit["id"],
                "title": hit["title"],
                "excerpt": excerpt,
                "revision": hit["revision"],
            }
            size = len(encoded(item).encode())
            if size > remaining:
                break
            result.append(item)
            remaining -= size
        return result

    async def recall_one(args, binding):
        hit = await memory.get(binding["owner"], args["memoryId"])
        offset = args.get("offset", 0)
        return {
            "id": hit["id"],
            "title": hit["title"],
            "body": hit["body"][offset : offset + 2000],
            "sources": hit["sources"],
            "nextOffset": offset + 2000 if len(hit["body"]) > offset + 2000 else None,
        }

    registry.add(
        Tool(
            "memory_get",
            "Read a source-backed memory in bounded pages.",
            object_schema(
                {"memoryId": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}},
                ["memoryId"],
            ),
            recall_one,
            main=True,
        )
    )

    registry.add(
        Tool(
            "delegate",
            "Delegate long work; returns a task immediately. Use fromMessageId only for a completed checkpoint Fork.",
            object_schema(
                {
                    "goal": {"type": "string", "minLength": 1, "maxLength": 20000},
                    "executor": {"type": "string", "enum": ["native", "codex", "claude"]},
                    "target": {"type": "object"},
                    "fromMessageId": {"type": "string"},
                },
                ["goal"],
            ),
            delegate,
            effect="write",
            main=True,
        )
    )
    registry.add(
        Tool("task_status", "Read delegated task status.", object_schema({}), status, main=True)
    )
    registry.add(
        Tool(
            "memory_search",
            "Retrieve source-backed memories only when relevant.",
            object_schema(
                {
                    "query": {"type": "string", "maxLength": 1000},
                    "scope": {"type": "string", "enum": ["conversation", "user"]},
                    "projectId": {"type": "string"},
                },
                ["query"],
            ),
            recall,
            main=True,
        )
    )
