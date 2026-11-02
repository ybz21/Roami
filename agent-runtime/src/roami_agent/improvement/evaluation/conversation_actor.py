"""Protocol-only Actor; live evaluation never constructs this scripted driver."""

import json

from roami_agent.protocol.models import ModelEvent


class ScriptedConversationActor:
    model = "conversation-protocol-fixture"

    def __init__(self):
        self.actions = []
        self.index = 0
        self.tasks = []
        self.rounds = 0
        self.prompts = []
        self.issued = {}
        self.processed = set()

    def turn(self, actions):
        self.actions, self.index = actions, 0

    def arguments(self, value):
        if isinstance(value, list):
            return [self.arguments(item) for item in value]
        if isinstance(value, dict):
            if set(value) in ({"task"}, {"revision"}):
                field = next(iter(value))
                matches = [task for task in self.tasks if value[field] in task["goal"]]
                if len(matches) != 1:
                    raise ValueError("Fixture must discover one task from real tool receipts")
                return matches[0]["id" if field == "task" else "revision"]
            return {key: self.arguments(item) for key, item in value.items()}
        return value

    async def stream(self, messages, tools):
        self.prompts.append(json.loads(json.dumps(messages)))
        for message in messages:
            call_id = message.get("tool_call_id")
            if message["role"] != "tool" or call_id not in self.issued or call_id in self.processed:
                continue
            self.processed.add(call_id)
            result = json.loads(message["content"])
            if isinstance(result, list):
                self.tasks = [
                    {
                        "id": item["id"],
                        "revision": item["revision"],
                        "goal": json.loads(item["intent_json"])["goal"],
                    }
                    for item in result
                    if "intent_json" in item
                ]
            elif (
                isinstance(result, dict)
                and result.get("taskId")
                and result.get("kind") == "background_task"
            ):
                previous = self.issued[call_id]
                self.tasks.append(
                    {"id": result["taskId"], "revision": 1, "goal": previous["args"]["goal"]}
                )
        if self.index >= len(self.actions):
            raise ValueError("Fixture exhausted before the real turn committed")
        action = self.actions[self.index]
        self.index += 1
        self.rounds += 1
        if "text" in action:
            yield ModelEvent("text", action["text"])
        else:
            self.issued[f"scenario-{self.rounds}"] = action
            yield ModelEvent(
                "tool",
                {
                    "id": f"scenario-{self.rounds}",
                    "type": "function",
                    "function": {
                        "name": action["tool"],
                        "arguments": json.dumps(self.arguments(action["args"]), ensure_ascii=False),
                    },
                },
            )
        yield ModelEvent(
            "usage",
            {"inputTokens": 100, "outputTokens": 20, "requestAttempts": 1, "retryUsageKnown": True},
        )
