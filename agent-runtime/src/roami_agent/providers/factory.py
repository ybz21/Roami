"""Construct the protocol client for the configured Go model gateway."""

import hashlib

from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.providers.local_gateway import local_gateway_client
from roami_agent.providers.request_policy import request_identity


def configured_provider(settings, role, *, client=None):
    route = settings.route(role)
    transport = client or local_gateway_client(
        role if role in {"main", "worker", "memory"} else "worker",
        route.timeout_seconds,
        socket=settings.model_gateway_socket,
        route_id=hashlib.sha256(
            (route.endpoint.rstrip("/") + "\x00" + route.name).encode()
        ).hexdigest(),
    )
    provider = ChatCompletions(
        route.endpoint if client else "http://localhost/v1",
        route.name,
        settings.credentials(role) if client else "",
        timeout=route.timeout_seconds,
        max_retries=route.max_retries,
        capabilities=route.capabilities,
        cache=route.cache,
        parameters=route.parameters,
        client=transport,
    )
    # Cache identity follows the saved route, not the private transport address.
    provider.provider_key, provider.settings_hash = request_identity(
        route.endpoint, route.name, provider.capabilities, provider.cache, provider.parameters
    )
    return provider
