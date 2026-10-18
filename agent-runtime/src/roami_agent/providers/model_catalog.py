"""Read provider-advertised context windows without inventing model capacities."""

import json

import httpx

from roami_agent.protocol.errors import DomainError


def context_window(item):
    for key in ("context_window", "contextWindow", "context_length", "max_context_tokens"):
        value = item.get(key)
        if type(value) is int and 1 <= value <= 100_000_000:
            return value
    for container in ("token_limits", "top_provider", "limits"):
        limits = item.get(container)
        if isinstance(limits, dict):
            for key in ("context_window", "contextWindow", "context_length", "max_context_tokens"):
                value = limits.get(key)
                if type(value) is int and 1 <= value <= 100_000_000:
                    return value
    return None


async def fetch_catalog(endpoint, key):
    headers = {"Authorization": "Bearer " + key} if key else {}
    try:
        async with (
            httpx.AsyncClient(timeout=8, follow_redirects=False) as client,
            client.stream("GET", endpoint.rstrip("/") + "/models", headers=headers) as response,
        ):
            if response.status_code != 200:
                raise DomainError("MODEL_PROVIDER_UNAVAILABLE", 502)
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 2 * 1024 * 1024:
                    raise DomainError("MODEL_CATALOG_LIMIT", 502)
        value = json.loads(data)
        return {
            item["id"]: context_window(item)
            for item in value["data"]
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and 0 < len(item["id"]) <= 200
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise DomainError("MODEL_PROVIDER_UNAVAILABLE", 502) from None
