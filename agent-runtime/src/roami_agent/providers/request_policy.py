"""Explicit provider capabilities, stable cache settings and bounded retry delays."""

import hashlib
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded


def request_policy(capabilities=None, cache=None):
    if (capabilities is not None and not isinstance(capabilities, dict)) or (
        cache is not None and not isinstance(cache, dict)
    ):
        raise DomainError("INVALID_MODEL_POLICY")
    capabilities = dict(capabilities or {})
    cache = dict(cache or {})
    allowed = {
        "version",
        "tools",
        "stream_usage",
        "prompt_cache_key",
        "prompt_cache_options",
        "images",
    }
    if set(capabilities) - allowed or any(
        not isinstance(value, bool) for key, value in capabilities.items() if key != "version"
    ):
        raise DomainError("INVALID_MODEL_CAPABILITIES")
    version = capabilities.setdefault("version", "chat-v1")
    if not isinstance(version, str) or not 1 <= len(version) <= 100:
        raise DomainError("INVALID_MODEL_CAPABILITIES")
    capabilities.setdefault("tools", True)
    capabilities.setdefault("stream_usage", True)
    capabilities.setdefault("images", False)
    if set(cache) - {"namespace", "mode", "ttl"}:
        raise DomainError("INVALID_MODEL_CACHE_CONFIG")
    if "namespace" in cache and (
        not capabilities.get("prompt_cache_key")
        or not isinstance(cache["namespace"], str)
        or not 1 <= len(cache["namespace"]) <= 200
    ):
        raise DomainError("MODEL_CACHE_CAPABILITY_REQUIRED")
    if set(cache) & {"mode", "ttl"}:
        if not capabilities.get("prompt_cache_options"):
            raise DomainError("MODEL_CACHE_CAPABILITY_REQUIRED")
        if (
            cache.get("mode", "implicit") not in {"implicit", "explicit"}
            or cache.get("ttl", "30m") != "30m"
        ):
            raise DomainError("INVALID_MODEL_CACHE_CONFIG")
    return capabilities, cache


def request_identity(endpoint, model, capabilities, cache):
    provider = hashlib.sha256(endpoint.encode()).hexdigest()
    settings = hashlib.sha256(encoded([model, "chat-v1", capabilities, cache]).encode()).hexdigest()
    return "chat-completions:" + provider, settings


def retry_delay(header, attempt):
    delay = min(0.25 * (2**attempt), 2)
    if header:
        try:
            value = float(header)
        except ValueError:
            try:
                value = (parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                value = None
        if value is not None and math.isfinite(value):
            delay = max(0, value)
    return delay


def normalized_usage(raw, attempts):
    def count(value):
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        )

    details = raw.get("prompt_tokens_details") or {}
    details = details if isinstance(details, dict) else {}
    normalized = {
        "inputTokens": count(raw.get("prompt_tokens")),
        "outputTokens": count(raw.get("completion_tokens")),
        "cacheReadTokens": count(details.get("cached_tokens")),
        "cacheWriteTokens": None,
    }
    return dict(
        raw,
        **normalized,
        providerRaw=raw,
        knownFields=[name for name, value in normalized.items() if value is not None],
        requestAttempts=attempts,
        retryUsageKnown=attempts == 1,
    )
