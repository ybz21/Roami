"""Responses text events for RSI roles that explicitly forbid tools and continuation."""

import json
import secrets
import time

from roami_agent.improvement.domain.contracts import require


def text_messages(body, model):
    require(isinstance(body, dict), "RSI_CODEX_GATEWAY_INPUT")
    require(body.get("model") == model and body.get("stream") is True, "RSI_CODEX_GATEWAY_INPUT")
    require(
        all(body.get(key) is None or body.get(key) is False for key in ("background", "store")),
        "RSI_CODEX_GATEWAY_INPUT",
    )
    text = body.get("text") or {}
    require(
        isinstance(text, dict)
        and isinstance(text.get("format", {}), dict)
        and text.get("format", {}).get("type", "text") == "text",
        "RSI_CODEX_GATEWAY_INPUT",
    )
    require(not body.get("previous_response_id"), "RSI_CODEX_GATEWAY_CONTINUATION")
    require(body.get("tool_choice") in (None, "auto", "none"), "RSI_UNEXPECTED_MODEL_TOOL")
    messages = []
    if instructions := body.get("instructions"):
        require(isinstance(instructions, str), "RSI_CODEX_GATEWAY_INPUT")
        messages.append({"role": "system", "content": instructions})
    items = body.get("input")
    if isinstance(items, str):
        items = [{"role": "user", "content": items}]
    require(isinstance(items, list) and bool(items), "RSI_CODEX_GATEWAY_INPUT")
    for item in items:
        require(isinstance(item, dict), "RSI_CODEX_GATEWAY_INPUT")
        if item.get("type") == "additional_tools":
            # This is a client catalog declaration, not a tool call; RSI roles expose no tools.
            require(
                item.get("role") == "developer" and isinstance(item.get("tools"), list),
                "RSI_CODEX_GATEWAY_INPUT",
            )
            continue
        require(item.get("type", "message") == "message", "RSI_UNEXPECTED_MODEL_TOOL")
        role, content = item.get("role"), item.get("content")
        require(role in {"system", "developer", "user", "assistant"}, "RSI_CODEX_GATEWAY_INPUT")
        if isinstance(content, list):
            require(
                all(
                    isinstance(part, dict)
                    and part.get("type") in {"input_text", "output_text"}
                    and isinstance(part.get("text"), str)
                    for part in content
                ),
                "RSI_CODEX_GATEWAY_INPUT",
            )
            content = "\n".join(part["text"] for part in content)
        require(isinstance(content, str), "RSI_CODEX_GATEWAY_INPUT")
        messages.append({"role": "system" if role == "developer" else role, "content": content})
    require(bool(messages), "RSI_CODEX_GATEWAY_INPUT")
    return messages


class TextResponse:
    def __init__(self, writer, model):
        self.writer, self.model = writer, model
        self.id, self.item_id = "resp_" + secrets.token_hex(12), "msg_" + secrets.token_hex(12)
        self.sequence, self.created = 0, int(time.time())
        self.parts = []

    def response(self, status, *, output=None, usage=None, error=None):
        return {
            "id": self.id,
            "object": "response",
            "created_at": self.created,
            "status": status,
            "model": self.model,
            "output": output or [],
            "usage": usage,
            "error": error,
        }

    async def event(self, kind, **data):
        value = {"type": kind, "sequence_number": self.sequence, **data}
        self.sequence += 1
        self.writer.write(
            (
                "event: " + kind + "\ndata: " + json.dumps(value, ensure_ascii=False) + "\n\n"
            ).encode()
        )
        await self.writer.drain()

    async def start(self):
        await self.event("response.created", response=self.response("in_progress"))
        await self.event(
            "response.output_item.added",
            output_index=0,
            item={
                "id": self.item_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "status": "in_progress",
            },
        )
        await self.event(
            "response.content_part.added",
            item_id=self.item_id,
            output_index=0,
            content_index=0,
            part={"type": "output_text", "text": "", "annotations": []},
        )

    async def delta(self, text):
        self.parts.append(text)
        require(sum(map(len, self.parts)) <= 100000, "RSI_INVALID_MODEL_OUTPUT")
        await self.event(
            "response.output_text.delta",
            item_id=self.item_id,
            output_index=0,
            content_index=0,
            delta=text,
            logprobs=[],
        )

    async def complete(self, usage):
        require(
            all(
                type(usage.get(k)) is int and usage[k] >= 0 for k in ("inputTokens", "outputTokens")
            ),
            "RSI_USAGE_UNKNOWN",
        )
        part = {
            "type": "output_text",
            "text": "".join(self.parts),
            "annotations": [],
            "logprobs": [],
        }
        item = {
            "id": self.item_id,
            "type": "message",
            "role": "assistant",
            "content": [part],
            "status": "completed",
        }
        await self.event(
            "response.output_text.done",
            item_id=self.item_id,
            output_index=0,
            content_index=0,
            text=part["text"],
            logprobs=[],
        )
        await self.event(
            "response.content_part.done",
            item_id=self.item_id,
            output_index=0,
            content_index=0,
            part=part,
        )
        await self.event("response.output_item.done", output_index=0, item=item)
        measured = {
            "input_tokens": usage["inputTokens"],
            "output_tokens": usage["outputTokens"],
            "total_tokens": usage["inputTokens"] + usage["outputTokens"],
        }
        if type(usage.get("cacheReadTokens")) is int:
            measured["input_tokens_details"] = {"cached_tokens": usage["cacheReadTokens"]}
        await self.event(
            "response.completed", response=self.response("completed", output=[item], usage=measured)
        )

    async def failed(self, code):
        await self.event(
            "response.failed",
            response=self.response("failed", error={"code": code, "message": code}),
        )
