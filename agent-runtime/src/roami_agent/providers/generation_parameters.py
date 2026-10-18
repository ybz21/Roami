"""Allow bounded generation controls without overriding routing, tools or transport."""

import math

from roami_agent.protocol.errors import DomainError


def generation_parameters(raw=None):
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - {
        "temperature",
        "top_p",
        "max_tokens",
        "reasoning_effort",
    }:
        raise DomainError("INVALID_MODEL_PARAMETERS")
    result = dict(raw)
    for name, lower, upper in (("temperature", 0, 2), ("top_p", 0, 1)):
        if name in result:
            value = result[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not lower <= value <= upper
                or not math.isfinite(value)
            ):
                raise DomainError("INVALID_MODEL_PARAMETERS")
    if "max_tokens" in result and (
        type(result["max_tokens"]) is not int or not 1 <= result["max_tokens"] <= 1_000_000
    ):
        raise DomainError("INVALID_MODEL_PARAMETERS")
    if "reasoning_effort" in result and result["reasoning_effort"] not in (
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ):
        raise DomainError("INVALID_MODEL_PARAMETERS")
    return result
