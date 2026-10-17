"""Main can manage explicitly requested reminders in its current conversation."""

from roami_agent.protocol.tools import Tool, object_schema


def register_reminder_tools(registry, reminders, timezone_name):
    async def create(args, binding):
        return await reminders.create(
            binding["owner"],
            binding["conversation"],
            args["text"],
            binding["turnId"] + ":" + binding["toolCallId"],
            when_ms=args.get("whenMs"),
            daily_at=args.get("dailyAt"),
            after_seconds=args.get("afterSeconds"),
            timezone_name=args.get("timezone", timezone_name),
            source_turn_id=binding["turnId"],
        )

    async def listing(args, binding):
        items = await reminders.list(binding["owner"], binding["conversation"])
        return {
            "nowMs": reminders.clock(),
            "timezone": timezone_name,
            "reminders": [
                {**item, "spec": {**item["spec"], "text": item["spec"]["text"][:300]}}
                for item in items[:20]
            ],
            "truncated": len(items) > 20,
        }

    async def cancel(args, binding):
        return await reminders.cancel(
            binding["owner"],
            args["id"],
            conversation_id=binding["conversation"],
            source_turn_id=binding["turnId"],
        )

    registry.add(
        Tool(
            "reminder_create",
            "Create only a reminder explicitly requested by the user. Choose exactly one: afterSeconds (relative delay), whenMs (UTC epoch milliseconds), dailyAt (HH:MM in timezone). Return the persisted nextDueMs; do not claim a device notification was delivered. Ask if the intended time is ambiguous.",
            object_schema(
                {
                    "text": {"type": "string", "minLength": 1, "maxLength": 10000},
                    "afterSeconds": {"type": "integer", "minimum": 1, "maximum": 2678400},
                    "whenMs": {"type": "integer", "minimum": 0, "maximum": 8000000000000},
                    "dailyAt": {"type": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]$"},
                    "timezone": {"type": "string", "maxLength": 100},
                },
                ["text"],
            ),
            create,
            effect="write",
            main=True,
        )
    )
    registry.add(
        Tool(
            "reminder_list",
            "List current conversation reminders and the runtime clock; bounded to 20, active first.",
            object_schema({}),
            listing,
            main=True,
        )
    )
    registry.add(
        Tool(
            "reminder_cancel",
            "Cancel a known reminder in this conversation when the user asks; existing messages remain.",
            object_schema({"id": {"type": "string", "minLength": 1, "maxLength": 200}}, ["id"]),
            cancel,
            effect="write",
            main=True,
        )
    )
