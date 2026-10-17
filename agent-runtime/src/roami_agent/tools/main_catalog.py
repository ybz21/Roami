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
        day = args.get("scope") == "day"
        day_key = args.get("dayKey")
        timezone = args.get("timezone") or memory.daily.timezone
        if day:
            from roami_agent.memory.daily import event_day
            from roami_agent.protocol.identity import now_ms

            day_key = day_key or event_day(now_ms(), timezone)
            await memory.daily.refresh(binding["owner"], day_key, timezone)
        result = await memory.recall(
            binding["owner"],
            "" if day else args["query"],
            conversation_id=binding["conversation"]
            if args.get("scope", "conversation") == "conversation"
            else None,
            project_id=args.get("projectId"),
            day_key=day_key if day else None,
            timezone=timezone if day else None,
            limit=8,
            include_global=not day,
        )
        packed, remaining = [], 6000
        for hit in result["hits"]:
            item = {
                "id": hit["id"],
                "title": hit["title"],
                "excerpt": hit["body"][:500],
                "revision": hit["revision"],
                "sourceRefs": hit["sourceRefs"],
                "scope": hit["scope"],
                "rankReason": hit["rankReason"],
            }
            size = len(encoded(item).encode())
            if size > remaining:
                result["truncated"] = True
                break
            packed.append(item)
            remaining -= size
        result["hits"] = packed
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
                    "scope": {"type": "string", "enum": ["conversation", "user", "day"]},
                    "projectId": {"type": "string"},
                    "dayKey": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
                    "timezone": {"type": "string", "maxLength": 100},
                },
                ["query"],
            ),
            recall,
            main=True,
        )
    )
