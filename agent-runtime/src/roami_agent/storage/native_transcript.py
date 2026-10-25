"""Bounded tool payloads for the native conversation renderer."""

import json

from roami_agent.conversation.activity_payloads import preview


def native_content(content, role, tool_state=None):
    value = dict(content)
    if role == "tool":
        text = value.get("text", "")
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            payload = text
        result = preview(payload)
        value["text"] = result["text"] + ("\n…[truncated]" if result["truncated"] else "")
        value["toolState"] = tool_state or "unknown"
    elif isinstance(value.get("tool_calls"), list):
        calls = []
        for call in value["tool_calls"]:
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                continue
            function = call["function"]
            arguments = function.get("arguments", "")
            try:
                arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            except ValueError:
                pass
            result = preview(arguments)
            calls.append(
                {
                    "id": call.get("id"),
                    "function": {
                        "name": function.get("name"),
                        "arguments": result["text"]
                        + ("\n…[truncated]" if result["truncated"] else ""),
                    },
                }
            )
        value["tool_calls"] = calls
    return value
