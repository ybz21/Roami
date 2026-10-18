"""Pi-style chars/4 estimates; provider usage includes cached input already."""

import hashlib
import math
from dataclasses import asdict

from roami_agent.protocol.serialization import encoded

ESTIMATOR = "pi-usage-plus-chars-v1"
IMAGE_TOKENS = 1200


def text_tokens(text):
    return math.ceil(len(text) / 4)


def message_tokens(message):
    content = message.get("content", "")
    if isinstance(content, str):
        count = text_tokens(content)
    else:
        count = sum(
            IMAGE_TOKENS
            if part.get("type") in {"image", "image_url"}
            else text_tokens(part.get("text", ""))
            for part in content
        )
    calls = message.get("tool_calls")
    return count + (text_tokens(encoded(calls)) if calls else 0)


def messages_tokens(messages):
    return sum(message_tokens(message) for message in messages)


def request_tokens(messages, catalog):
    return messages_tokens(messages) + (text_tokens(encoded(catalog)) if catalog else 0)


def request_basis(context):
    return hashlib.sha256(encoded(context).encode()).hexdigest()


def request_context(settings, instructions, catalog, role="main"):
    return {
        "instructions": instructions,
        "catalog": catalog,
        "route": asdict(settings.route(role)),
        "inputBudget": settings.context_input_budget,
        "contextWindow": settings.context_window,
        "reserveTokens": settings.reserve_tokens,
        "compactionThreshold": settings.compaction_threshold,
        "compactionRatio": settings.compaction_ratio,
        "capacityBasis": "model_window" if settings.context_window else "input_budget",
    }


def provider_tokens(usage):
    if not isinstance(usage, dict):
        return None

    def count(*keys):
        for key in keys:
            value = usage.get(key)
            if type(value) is int and value >= 0:
                return value
        return None

    incoming = count("inputTokens", "prompt_tokens")
    outgoing = count("outputTokens", "completion_tokens")
    if incoming is None or incoming == 0 or outgoing is None:
        return None
    # OpenAI-compatible prompt_tokens already includes cache reads/writes.
    return incoming + outgoing
