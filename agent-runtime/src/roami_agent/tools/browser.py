"""Worker-only Browser Use; actions always reference a durable observation."""

from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.observation_inputs import observation_input, resource_input


def register_browser_tools(registry, driver):
    async def observe(args, binding):
        return await driver.observe(await resource_input(driver, args, binding, "browser"), binding)

    async def act(args, binding):
        return await driver.act(await observation_input(driver, args, binding, "browser"), binding)

    registry.add(
        Tool(
            "browser_open",
            "Open a task-owned background tab in the configured browser, preserving its login state. Do not open a replacement after an unknown result or human takeover. A returned resourceId with an observation error must be observed, not recreated.",
            object_schema(
                {
                    "url": {"type": "string", "maxLength": 4000},
                    "targetId": {"type": "string", "maxLength": 128},
                }
            ),
            driver.open,
            effect="write",
        )
    )
    registry.add(
        Tool(
            "browser_observe",
            "Passively observe this task's browser resource, obtaining its current observation ID, visible controls and screenshot evidence. It does not take input focus. DOM scope is the main frame; truncated data is marked.",
            object_schema(
                {"resourceId": {"type": "string", "minLength": 1, "maxLength": 128}}, ["resourceId"]
            ),
            observe,
        )
    )
    registry.add(
        Tool(
            "browser_act",
            "Perform one bounded action based on the latest observation. Upload selects a readable absolute file inside the prepared task workspace; it does not confirm server upload or publication. A successful action is not task acceptance. On a scene change, observe again. An unknown outcome must stop unless navigationRecoveryAvailable=true explicitly permits observing the stopped navigation in the same tab. Human takeover always stops input.",
            {
                "type": "object",
                "properties": {
                    "observationId": {"type": "string", "minLength": 1, "maxLength": 128},
                    "kind": {
                        "type": "string",
                        "enum": ["click", "fill", "type", "press", "goto", "upload"],
                    },
                    "selector": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "text": {"type": "string", "maxLength": 8000},
                    "path": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    "key": {"type": "string", "minLength": 1, "maxLength": 100},
                    "url": {"type": "string", "minLength": 1, "maxLength": 4000},
                },
                "required": ["observationId", "kind"],
                "additionalProperties": False,
                "allOf": [
                    {
                        "if": {
                            "properties": {"kind": {"enum": ["click", "fill", "type", "upload"]}}
                        },
                        "then": {"required": ["selector"]},
                    },
                    {
                        "if": {"properties": {"kind": {"enum": ["fill", "type"]}}},
                        "then": {"required": ["text"]},
                    },
                    {
                        "if": {"properties": {"kind": {"const": "press"}}},
                        "then": {"required": ["key"]},
                    },
                    {
                        "if": {"properties": {"kind": {"const": "upload"}}},
                        "then": {"required": ["path"]},
                    },
                    {
                        "if": {"properties": {"kind": {"const": "goto"}}},
                        "then": {"required": ["url"]},
                    },
                ],
            },
            act,
            effect="write",
        )
    )
