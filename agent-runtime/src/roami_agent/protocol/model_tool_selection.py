"""Request-local selection for recovering an unsubmitted Main answer."""

from contextlib import asynccontextmanager
from contextvars import ContextVar

from roami_agent.protocol.errors import DomainError

required_final_reply = ContextVar("required_final_reply", default=False)


def final_reply_choice():
    return {"type": "function", "function": {"name": "reply"}}


def selected_reply_tool(tools):
    if not required_final_reply.get():
        return None
    if not any(
        isinstance(tool, dict)
        and tool.get("type") == "function"
        and isinstance(tool.get("function"), dict)
        and tool["function"].get("name") == "reply"
        for tool in tools
    ):
        raise DomainError("MODEL_REPLY_TOOL_REQUIRED")
    return final_reply_choice()


@asynccontextmanager
async def select_final_reply(required=False):
    token = required_final_reply.set(required)
    try:
        yield
    finally:
        required_final_reply.reset(token)
