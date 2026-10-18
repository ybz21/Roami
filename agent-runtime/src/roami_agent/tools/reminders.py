"""Main can manage explicitly requested reminders in its current conversation."""

from roami_agent.protocol.tools import Tool, object_schema


def register_reminder_tools(registry, reminders, timezone_name, policy=None, briefs=None):
    async def timezone(owner):
        return (await policy.get(owner))["timezone"] if policy else timezone_name

    async def create(args, binding):
        selected_timezone = args.get("timezone") or await timezone(binding["owner"])
        if args.get("kind") == "daily_brief":
            from roami_agent.protocol.errors import DomainError

            if not briefs or args.get("afterSeconds") is not None or args.get("whenMs") is not None:
                raise DomainError("INVALID_BRIEF_SCHEDULE")
            item = await briefs.create(
                binding["owner"],
                binding["conversation"],
                args["text"],
                binding["turnId"] + ":" + binding["toolCallId"],
                daily_at=args.get("dailyAt"),
                timezone_name=selected_timezone,
                source_turn_id=binding["turnId"],
            )
            return dict(item, id="brief:" + item["id"], kind="daily_brief")
        return await reminders.create(
            binding["owner"],
            binding["conversation"],
            args["text"],
            binding["turnId"] + ":" + binding["toolCallId"],
            when_ms=args.get("whenMs"),
            daily_at=args.get("dailyAt"),
            after_seconds=args.get("afterSeconds"),
            timezone_name=selected_timezone,
            source_turn_id=binding["turnId"],
        )

    async def listing(args, binding):
        items = await reminders.list(binding["owner"], binding["conversation"])
        if briefs:
            items += await briefs.reminders(binding["owner"], binding["conversation"])
        items.sort(key=lambda item: (not item["enabled"], -item["createdMs"]))
        return {
            "nowMs": reminders.clock(),
            "timezone": await timezone(binding["owner"]),
            "reminders": [
                {**item, "spec": {**item["spec"], "text": item["spec"]["text"][:300]}}
                for item in items[:20]
            ],
            "truncated": len(items) > 20,
        }

    async def cancel(args, binding):
        if briefs and args["id"].startswith("brief:"):
            return await briefs.cancel(
                binding["owner"],
                args["id"][6:],
                conversation_id=binding["conversation"],
                source_turn_id=binding["turnId"],
            )
        return await reminders.cancel(
            binding["owner"],
            args["id"],
            conversation_id=binding["conversation"],
            source_turn_id=binding["turnId"],
        )

    registry.add(
        Tool(
            "reminder_create",
            "Create only an explicitly requested reminder. kind=daily_brief schedules a short model-generated brief of yesterday's recorded conversation activity; it requires dailyAt and has a separate background budget. Otherwise choose exactly one: afterSeconds, whenMs (UTC epoch milliseconds), dailyAt (HH:MM in timezone). Return persisted nextDueMs, never claim device delivery. Ask if time is ambiguous.",
            object_schema(
                {
                    "text": {"type": "string", "minLength": 1, "maxLength": 10000},
                    "kind": {"type": "string", "enum": ["reminder", "daily_brief"]},
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
