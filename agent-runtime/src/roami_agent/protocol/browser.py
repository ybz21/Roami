"""Explicit Browser Use configuration; no driver is enabled by default."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import model_endpoint


def browser_config(value):
    if not isinstance(value, dict) or set(value) - {
        "enabled",
        "endpoint",
        "existing_tabs",
        "max_tabs",
    }:
        raise DomainError("INVALID_BROWSER_CONFIG")
    if not value:
        return {}
    result = {
        "enabled": value.get("enabled", True),
        "existing_tabs": value.get("existing_tabs", False),
        "endpoint": model_endpoint(value.get("endpoint", "")),
        "max_tabs": value.get("max_tabs", 0),
    }
    if (
        not isinstance(result["enabled"], bool)
        or not isinstance(result["existing_tabs"], bool)
        or not isinstance(result["max_tabs"], int)
        or isinstance(result["max_tabs"], bool)
        or result["max_tabs"] < 0
    ):
        raise DomainError("INVALID_BROWSER_CONFIG")
    return result
