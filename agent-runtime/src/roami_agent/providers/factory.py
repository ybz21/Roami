"""Construct the protocol client for the configured Go model gateway."""

from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.providers.local_gateway import local_gateway_client


def configured_provider(settings, role, *, client=None):
    route = settings.route(role)
    provider = ChatCompletions(
        route.endpoint,
        route.name,
        settings.credentials(role),
        timeout=route.timeout_seconds,
        max_retries=route.max_retries,
        capabilities=route.capabilities,
        cache=route.cache,
        parameters=route.parameters,
        client=client
        or local_gateway_client(role, route.timeout_seconds, socket=settings.model_gateway_socket),
    )
    return provider
