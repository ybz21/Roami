"""Explicit Browser Use configuration; no driver is enabled by default."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import model_endpoint


def browser_config(value):
    if not isinstance(value, dict) or set(value) - {
        "enabled",
        "endpoint",
        "existing_tabs",
        "max_tabs",
        "idle_timeout_seconds",
    }:
        raise DomainError("INVALID_BROWSER_CONFIG")
    if not value:
        return {}
    result = {
        "enabled": value.get("enabled", True),
        "existing_tabs": value.get("existing_tabs", False),
        "endpoint": model_endpoint(value.get("endpoint", "")),
        "max_tabs": value.get("max_tabs", 20),
        "idle_timeout_seconds": value.get("idle_timeout_seconds", 600),
    }
    if (
        not isinstance(result["enabled"], bool)
        or not isinstance(result["existing_tabs"], bool)
        or not isinstance(result["max_tabs"], int)
        or isinstance(result["max_tabs"], bool)
        or not 1 <= result["max_tabs"] <= 20
        or type(result["idle_timeout_seconds"]) is not int
        or not 30 <= result["idle_timeout_seconds"] <= 86400
    ):
        raise DomainError("INVALID_BROWSER_CONFIG")
    return result
