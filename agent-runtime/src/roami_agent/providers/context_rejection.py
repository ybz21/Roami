"""Classify explicit context rejection without exposing private provider diagnostics."""

import asyncio
import json
import re

import httpx

CONTEXT_CODES = frozenset(
    {"context_length_exceeded", "context_window_exceeded", "prompt_too_long", "input_too_long"}
)
CONTEXT_MESSAGE = re.compile(
    r"\A\s*(?:input|prompt|messages?).{0,80}\b(?:exceeds?|exceeded|too long)\b"
    r".{0,80}\b(?:context|tokens?)\b"
    r"|\A\s*(?:this model's )?(?:maximum|max) context length\b.{0,60}\btokens?\b"
    r".{0,80}\b(?:requested|resulted|exceed)",
    re.IGNORECASE,
)


async def context_rejected(response):
    if response.status_code != 400:
        return False
    body = bytearray()
    try:
        async with asyncio.timeout(1):
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > 16_384:
                    return False
                body.extend(chunk)
    except (httpx.HTTPError, TimeoutError):
        return False
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        return False
    error = value.get("error", value) if isinstance(value, dict) else None
    if not isinstance(error, dict):
        return False
    code, message = error.get("code"), error.get("message")
    return (isinstance(code, str) and code in CONTEXT_CODES) or (
        isinstance(message, str) and CONTEXT_MESSAGE.search(message) is not None
    )
