"""Short Main tools bound to conversation-scoped application services."""

from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool, object_schema


def register_main_tools(registry, tasks, memory, targets):
    async def send_message(args, binding):
        return await targets.send(
            args["sessionId"], args["text"], binding["turnId"] + ":" + binding["toolCallId"]
        )

    registry.add(
        Tool(
            "session_send",
            "Append the user's message or work instructions to one exact existing live session. "
            "Works with legacy Codex/Claude sessions without lifecycle callbacks. Returns delivery only, "
            "NOT task completion; executionTracked=false means results must be checked separately. "
            "Use when the user explicitly asks to message or continue an existing session. Never guess a target. "
            "For a new session/project or tracked task use delegate instead. Do not retry unknown outcomes.",
            object_schema(
                {
                    "sessionId": {"type": "string", "minLength": 1, "maxLength": 300},
                    "text": {"type": "string", "minLength": 1, "maxLength": 100000},
                },
                ["sessionId", "text"],
            ),
            send_message,
            main=True,
            effect="write",
        )
    )

    async def overview(args, binding):
        return await targets.overview()

    registry.add(
        Tool(
            "workspace_overview",
            "Count projects and sessions on the current Roami node in one CLI call. "
            "Includes project/loose and live/dormant session totals. Use for count or overview "
            "questions; do not count truncated project top cards or page through target_search.",
            object_schema({}),
            overview,
            main=True,
        )
    )

    async def target_search(args, binding):
        return await targets.search(
            args["kind"],
            args.get("query", ""),
            offset=args.get("offset", 0),
            limit=args.get("limit", 10),
        )

    async def target_resolve(args, binding):
        return await targets.resolve(args["kind"], args["id"])

    registry.add(
        Tool(
            "target_search",
            "Find projects or live sessions by literal name/ID, with bounded pages. Use one exact unique match directly; never guess among duplicate names. session_send appends to legacy sessions; tracked task continuation requires lifecycle callbacks.",
            object_schema(
                {
                    "kind": {"type": "string", "enum": ["project", "session"]},
                    "query": {"type": "string", "maxLength": 200},
                    "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                ["kind"],
            ),
            target_search,
            main=True,
        )
    )
    registry.add(
        Tool(
            "target_resolve",
            "Resolve an exact project ID or live session ID/name/label; duplicate labels fail. Liveness does not prove a task finished or stopped.",
            object_schema(
                {
                    "kind": {"type": "string", "enum": ["project", "session"]},
                    "id": {"type": "string", "minLength": 1, "maxLength": 300},
                },
                ["kind", "id"],
            ),
            target_resolve,
            main=True,
        )
    )

    async def delegate(args, binding):
        return await tasks.create(
            binding["owner"],
            binding["conversation"],
            args["goal"],
            key=binding["turnId"] + ":" + binding["toolCallId"],
            source_turn_id=binding["turnId"],
            source_assistant_message_id=binding["assistantMessageId"],
            parent_task_id=binding.get("taskId"),
            executor=args.get("executor", "native"),
            target=args.get("target"),
            from_message_id=args.get("fromMessageId"),
            origin_message_id=binding["originMessageId"],
        )

    async def status(args, binding):
        return await tasks.list(binding["owner"], binding["conversation"], for_model=True)

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
                    "target": {
                        **object_schema(
                            {
                                "kind": {
                                    "type": "string",
                                    "enum": ["project", "session", "new_session", "new_project"],
                                },
                                "projectId": {"type": "string", "minLength": 1, "maxLength": 300},
                                "sessionId": {"type": "string", "minLength": 1, "maxLength": 300},
                                "workspaceId": {"type": "string", "minLength": 1, "maxLength": 300},
                                "directory": {"type": "string", "maxLength": 2000},
                                "name": {"type": "string", "maxLength": 200},
                                "baseDir": {"type": "string", "maxLength": 2000},
                                "base": {"type": "string", "maxLength": 300},
                                "remote": {"type": "string", "maxLength": 300},
                                "nodeId": {"type": "string", "enum": ["local"]},
                                "label": {"type": "string", "maxLength": 160},
                                "archived": {"type": "boolean"},
                                "state": {"type": "string", "enum": ["live"]},
                            },
                            ["kind"],
                        ),
                        "description": "For an existing session use ONLY kind=session and exact sessionId (plus nodeId/label). Never add directory/workspaceId/base/remote. A projectId is descriptive context only and cannot override the exact session. kind=project + projectId prepares a worktree; workspaceId reuses it without base/remote/directory overrides. kind=new_project + name (+ absolute baseDir) creates a separate project. kind=new_session starts loose work. Reuse preserves local work.",
                    },
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
