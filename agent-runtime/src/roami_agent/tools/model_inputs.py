"""Small tool inputs; execution bookkeeping stays in the application handlers."""

from copy import deepcopy

from roami_agent.protocol.tools import object_schema

INPUTS = {
    "bash": ("command timeout", "command"),
    "read": ("path offset limit", "path"),
    "write": ("path content", "path content"),
    "edit": ("path oldText newText", "path oldText newText"),
    "tool_list": ("query kind offset", ""),
    "delegate": ("goal executor directory projectId sessionId fromMessageId", "goal"),
    "ask_user": ("prompt options", "prompt"),
    "reply": ("text json", ""),
    "task_reply": ("taskId", "taskId"),
    "task_queue_reply": ("", ""),
    "task_steer": ("taskId text", "taskId text"),
    "memory_search": ("query scope projectId dayKey", "query"),
    "reminder_create": ("text kind afterSeconds whenMs dailyAt", "text"),
    "browser_observe": ("resourceId", ""),
    "browser_act": ("kind selector text key url path sha256 resourceId", "kind"),
    "computer_observe": ("resourceId focusOnly", ""),
    "computer_act": ("kind x y button amount key text", "kind"),
}

DESCRIPTIONS = {
    "bash": "Execute a shell command in the current working directory. Optionally set timeout in seconds.",
    "read": "Read a file, image, skill:// path or artifact:// ID. Text offset and limit are in lines, starting at 1.",
    "write": "Write UTF-8 content to a file. The host checks for changes since the last read.",
    "edit": "Replace one exact occurrence of oldText with newText. Read the file before editing.",
    "tool_list": "Find installed skills, tools and CLI commands. Use nextOffset to read another page.",
    "delegate": "Delegate a task. Omit executor for the configured default, or choose native for in-process work. Optionally select a directory, project or existing session. Acceptance is pending work; handle any remaining user requests, then finish without polling.",
    "ask_user": "Ask for missing information or a decision. Optional choices are short strings, recommended first.",
    "reply": "Submit the final answer. Use text for prose or json for requested JSON, never both. Call alone, without a preamble.",
    "task_reply": "Answer a progress question about one task using its current recorded state.",
    "task_queue_reply": "Answer whether any tasks are still running using the current recorded queue.",
    "task_steer": "Continue an existing task with new instructions. Its executor and workspace are preserved.",
    "memory_search": "Search relevant saved memories. Scope and date filters are optional.",
    "reminder_create": "Create a requested reminder. Choose afterSeconds, whenMs or dailyAt; the saved timezone is used. kind=daily_brief requests a daily generated summary.",
    "browser_observe": "Observe the current browser tab. Select resourceId only when more than one tab is owned.",
    "browser_act": "Act on the last browser observation seen in this conversation. Choose click, fill, type, press, goto or upload and its target/value. Upload needs selector and an absolute path in the prepared workspace; observe afterward to verify server results.",
    "computer_observe": "Observe the current desktop. Optionally crop to its focused window.",
    "computer_act": "Act on the current screenshot: click or scroll at x/y, send a key, or type text.",
}


def register_model_inputs(registry):
    for name, (fields, required) in INPUTS.items():
        tool = registry.registry.get(name)
        if tool is None or tool.source != "builtin":
            continue
        properties = tool.schema.get("properties", {})
        public = {key: deepcopy(properties[key]) for key in fields.split() if key in properties}
        if name == "ask_user":
            public["options"] = {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 2,
                "maxItems": 4,
            }
        if name == "read":
            public["offset"] = {
                "type": "integer",
                "minimum": 1,
                "description": "Starting line (1-indexed).",
            }
            public["limit"] = {
                "type": "integer",
                "minimum": 1,
                "maximum": 2000,
                "description": "Maximum lines to read.",
            }
        if name == "browser_act":
            public["resourceId"] = {"type": "string", "minLength": 1, "maxLength": 128}
        schema = object_schema(public, required.split())
        if "allOf" in tool.schema:
            schema["allOf"] = deepcopy(tool.schema["allOf"])
        tool.model_schema = schema
        tool.description = DESCRIPTIONS[name]
