"""Construct the protocol client for the configured Go model gateway."""

from roami_agent.providers.chat_completions import ChatCompletions


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
        client=client,
    )
    return provider
