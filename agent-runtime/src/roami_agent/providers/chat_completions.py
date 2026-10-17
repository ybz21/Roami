"Streaming chat-completions adapter; the loop depends only on normalized events."

import json

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent


class ChatCompletions:
    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "",
        *,
        timeout: float = 90,
        client: httpx.AsyncClient | None = None,
    ):
        self.endpoint, self.model, self.api_key = endpoint.rstrip("/"), model, api_key
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10), follow_redirects=False
        )

    async def stream(self, messages, tools):
        if not self.model or not self.endpoint:
            raise DomainError("MODEL_NOT_CONFIGURED", 503)
        headers = {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
        calls, finished = {}, False
        async with self.client.stream(
            "POST", self.endpoint + "/chat/completions", headers=headers, json=body
        ) as response:
            if response.status_code >= 400:
                # Provider bodies can contain echoed prompts and credentials; do not relay them.
                raise DomainError("MODEL_HTTP_" + str(response.status_code), 502)
            async for line in response.aiter_lines():
                if len(line) > 1_000_000:
                    raise DomainError("MODEL_EVENT_TOO_LARGE", 502)
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    break
                data = json.loads(value)
                if data.get("usage"):
                    yield ModelEvent("usage", data["usage"])
                for choice in data.get("choices", []):
                    if choice.get("index", 0) != 0:
                        continue
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        yield ModelEvent("text", delta["content"])
                    for part in delta.get("tool_calls", []):
                        key = part["index"]
                        if key not in calls and len(calls) >= 16:
                            raise DomainError("TOOL_CALL_LIMIT", 502)
                        call = calls.setdefault(
                            key,
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        call["id"] += part.get("id", "")
                        for field in ["name", "arguments"]:
                            call["function"][field] += part.get("function", {}).get(field, "")
                        if len(call["function"]["arguments"]) > 100_000:
                            raise DomainError("TOOL_ARGUMENTS_TOO_LARGE", 502)
                    reason = choice.get("finish_reason")
                    if reason:
                        if reason not in {"stop", "tool_calls"}:
                            raise DomainError("MODEL_OUTPUT_" + reason.upper(), 502)
                        finished = True
            if not finished:
                raise DomainError("MODEL_STREAM_INCOMPLETE", 502)
            for index in sorted(calls):
                call = calls[index]
                if not call["id"] or not call["function"]["name"]:
                    raise DomainError("MODEL_TOOL_CALL_INCOMPLETE", 502)
                json.loads(call["function"]["arguments"])
                yield ModelEvent("tool", call)

    async def close(self):
        await self.client.aclose()
