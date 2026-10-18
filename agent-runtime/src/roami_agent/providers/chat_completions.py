"Streaming chat-completions adapter; the loop depends only on normalized events."

import asyncio
import hashlib
import json
import math
import time
from copy import deepcopy

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent, model_endpoint
from roami_agent.protocol.serialization import encoded
from roami_agent.providers.generation_parameters import generation_parameters
from roami_agent.providers.request_policy import (
    normalized_usage,
    request_identity,
    request_policy,
    retry_delay,
)


class RetryableResponse(Exception):
    def __init__(self, status, delay):
        self.status, self.delay = status, delay


class ChatCompletions:
    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "",
        *,
        timeout: float = 90,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        capabilities: dict | None = None,
        cache: dict | None = None,
        parameters: dict | None = None,
        sleep=asyncio.sleep,
    ):
        self.endpoint, self.model, self.api_key = model_endpoint(endpoint), model, api_key
        if (
            not isinstance(model, str)
            or not isinstance(max_retries, int)
            or isinstance(max_retries, bool)
            or not 0 <= max_retries <= 3
            or not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise DomainError("INVALID_MODEL_CONFIG")
        self.capabilities, self.cache = request_policy(capabilities, cache)
        self.parameters = generation_parameters(parameters)
        self.provider_key, self.settings_hash = request_identity(
            self.endpoint, model, self.capabilities, self.cache, self.parameters
        )
        self.timeout, self.max_retries, self.sleep = timeout, max_retries, sleep
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10), follow_redirects=False
        )

    async def stream(self, messages, tools):
        if not self.model or not self.endpoint:
            raise DomainError("MODEL_NOT_CONFIGURED", 503)
        if tools and not self.capabilities["tools"]:
            raise DomainError("MODEL_TOOLS_UNSUPPORTED")
        if not self.capabilities["images"] and any(
            isinstance(message.get("content"), list)
            and any(
                isinstance(part, dict) and part.get("type") == "image_url"
                for part in message["content"]
            )
            for message in messages
        ):
            raise DomainError("MODEL_IMAGES_UNSUPPORTED")
        deadline = time.monotonic() + self.timeout
        emitted = False
        try:
            async with asyncio.timeout(self.timeout):
                for attempt in range(self.max_retries + 1):
                    try:
                        async for event in self._stream_once(messages, tools, attempt):
                            emitted = True
                            yield event
                        return
                    except RetryableResponse as exc:
                        code, delay = "MODEL_HTTP_" + str(exc.status), exc.delay
                    except (
                        httpx.ConnectError,
                        httpx.ConnectTimeout,
                        httpx.ReadError,
                        httpx.ReadTimeout,
                        httpx.RemoteProtocolError,
                    ):
                        code, delay = "MODEL_TRANSPORT_FAILED", retry_delay(None, attempt)
                    if emitted or attempt >= self.max_retries:
                        raise DomainError(code, 502)
                    if delay >= deadline - time.monotonic():
                        raise DomainError("MODEL_RETRY_DEADLINE", 502)
                    await self.sleep(delay)
        except TimeoutError as exc:
            raise DomainError("MODEL_DEADLINE", 502) from exc
        except httpx.HTTPError as exc:
            raise DomainError("MODEL_TRANSPORT_FAILED", 502) from exc

    async def _stream_once(self, messages, tools, attempt):
        headers = {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
        body = {
            **self.parameters,
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if self.capabilities["stream_usage"]:
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
        if "namespace" in self.cache:
            prefix = [
                self.provider_key,
                self.settings_hash,
                self.cache["namespace"],
                messages[:1],
                tools,
            ]
            body["prompt_cache_key"] = hashlib.sha256(encoded(prefix).encode()).hexdigest()
        if set(self.cache) & {"mode", "ttl"}:
            body["prompt_cache_options"] = {
                "mode": self.cache.get("mode", "implicit"),
                "ttl": self.cache.get("ttl", "30m"),
            }
            if self.cache.get("mode") == "explicit":
                body["messages"] = deepcopy(messages)
                prefix = []
                for index, message in enumerate(body["messages"]):
                    if message.get("role") not in {"system", "developer"}:
                        break
                    prefix.append(index)
                if not prefix or not isinstance(body["messages"][prefix[-1]].get("content"), str):
                    raise DomainError("MODEL_CACHE_PREFIX_REQUIRED")
                last = body["messages"][prefix[-1]]
                last["content"] = [
                    {
                        "type": "text",
                        "text": last["content"],
                        "prompt_cache_breakpoint": {"mode": "explicit"},
                    }
                ]
        calls, finished = {}, False
        async with self.client.stream(
            "POST",
            self.endpoint + "/chat/completions",
            headers=headers,
            json=body,
            follow_redirects=False,
        ) as response:
            if response.status_code in {408, 429, 500, 502, 503, 504}:
                raise RetryableResponse(
                    response.status_code, retry_delay(response.headers.get("retry-after"), attempt)
                )
            if 300 <= response.status_code < 400:
                raise DomainError("MODEL_REDIRECT_BLOCKED", 502)
            if response.status_code >= 400:
                # Provider bodies can contain echoed prompts and credentials; do not relay them.
                raise DomainError("MODEL_HTTP_" + str(response.status_code), 502)
            lines = response.aiter_lines()
            async for line in lines:
                if len(line) > 1_000_000:
                    raise DomainError("MODEL_EVENT_TOO_LARGE", 502)
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    await self._drain_terminal_body(lines)
                    break
                try:
                    data = json.loads(value)
                except ValueError as exc:
                    raise DomainError("MODEL_STREAM_INVALID", 502) from exc
                if not isinstance(data, dict):
                    raise DomainError("MODEL_STREAM_INVALID", 502)
                if data.get("usage"):
                    if not isinstance(data["usage"], dict):
                        raise DomainError("MODEL_USAGE_INVALID", 502)
                    yield ModelEvent("usage", normalized_usage(data["usage"], attempt + 1))
                choices = data.get("choices", [])
                if not isinstance(choices, list):
                    raise DomainError("MODEL_STREAM_INVALID", 502)
                for choice in choices:
                    if not isinstance(choice, dict):
                        raise DomainError("MODEL_STREAM_INVALID", 502)
                    if choice.get("index", 0) != 0:
                        continue
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict) or (
                        delta.get("content") is not None and not isinstance(delta["content"], str)
                    ):
                        raise DomainError("MODEL_STREAM_INVALID", 502)
                    if delta.get("content"):
                        yield ModelEvent("text", delta["content"])
                    parts = delta.get("tool_calls") or []
                    if not isinstance(parts, list):
                        raise DomainError("MODEL_STREAM_INVALID", 502)
                    for part in parts:
                        if (
                            not isinstance(part, dict)
                            or not isinstance(part.get("index"), int)
                            or isinstance(part["index"], bool)
                            or not 0 <= part["index"] < 16
                        ):
                            raise DomainError("MODEL_STREAM_INVALID", 502)
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
                        function = part.get("function") or {}
                        if (
                            not isinstance(function, dict)
                            or not isinstance(part.get("id", ""), str)
                            or any(
                                not isinstance(function.get(field, ""), str)
                                for field in ["name", "arguments"]
                            )
                        ):
                            raise DomainError("MODEL_STREAM_INVALID", 502)
                        call["id"] += part.get("id", "")
                        for field in ["name", "arguments"]:
                            call["function"][field] += function.get(field, "")
                        if len(call["id"]) > 256 or len(call["function"]["name"]) > 200:
                            raise DomainError("MODEL_TOOL_CALL_INVALID", 502)
                        if len(call["function"]["arguments"]) > 100_000:
                            raise DomainError("TOOL_ARGUMENTS_TOO_LARGE", 502)
                    reason = choice.get("finish_reason")
                    if reason:
                        if not isinstance(reason, str):
                            raise DomainError("MODEL_STREAM_INVALID", 502)
                        if reason not in {"stop", "tool_calls"}:
                            raise DomainError(
                                "MODEL_OUTPUT_" + reason.upper()
                                if reason in {"length", "content_filter", "function_call"}
                                else "MODEL_FINISH_REASON_UNSUPPORTED",
                                502,
                            )
                        finished = True
            if not finished:
                raise DomainError("MODEL_STREAM_INCOMPLETE", 502)
            for index in sorted(calls):
                call = calls[index]
                if not call["id"] or not call["function"]["name"]:
                    raise DomainError("MODEL_TOOL_CALL_INCOMPLETE", 502)
                json.loads(call["function"]["arguments"])
                yield ModelEvent("tool", call)

    @staticmethod
    async def _drain_terminal_body(lines):
        # EOF returns a reusable HTTP connection; DONE alone may precede its final chunk.
        try:
            async with asyncio.timeout(0.05):
                for _ in range(8):
                    try:
                        await anext(lines)
                    except StopAsyncIteration:
                        break
        except (TimeoutError, httpx.HTTPError):
            pass

    async def close(self):
        await self.client.aclose()
