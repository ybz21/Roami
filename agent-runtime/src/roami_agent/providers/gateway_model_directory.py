"""Validate a configured node Gateway model before binding a scoped caller."""

import json
import os

import httpx

from roami_agent.protocol.errors import DomainError


async def require_gateway_model(socket, model, *, allow_metered):
    socket = socket or os.environ.get("ROAMI_MODEL_GATEWAY_SOCKET")
    if not socket:
        raise DomainError("MODEL_GATEWAY_REQUIRED", 503)
    transport = httpx.AsyncHTTPTransport(uds=socket, retries=0)
    try:
        async with (
            httpx.AsyncClient(transport=transport, timeout=5) as client,
            client.stream(
                "GET",
                "http://roami-model/v1/model-gateway/models",
                headers={"X-Roami-Owner": "local"},
                params={} if allow_metered else {"free": "true"},
            ) as response,
        ):
            response.raise_for_status()
            document = bytearray()
            async for chunk in response.aiter_bytes():
                document.extend(chunk)
                if len(document) > 2 * 1024 * 1024:
                    raise DomainError("MODEL_CATALOG_LIMIT", 502)
        entries = json.loads(document)["data"]["models"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        raise DomainError("MODEL_PROVIDER_UNAVAILABLE", 502) from None
    if not isinstance(entries, list):
        raise DomainError("MODEL_PROVIDER_UNAVAILABLE", 502)
    row = next((item for item in entries if isinstance(item, dict) and item.get("id") == model), {})
    if (
        row.get("enabled") is not True
        or row.get("configured") is not True
        or (
            not allow_metered
            and row.get("pricing") != "confirmed-free"
            and row.get("freeOnly") is not True
        )
    ):
        raise DomainError("MODEL_NOT_CONFIGURED", 409)
