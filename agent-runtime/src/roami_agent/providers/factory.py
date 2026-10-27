"""Construct a configured model and attach inherited node accounting once."""

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
    from roami_agent.providers.model_proxy import model_proxy_context

    proxy = model_proxy_context.get()
    return proxy.attach(provider, role) if proxy is not None else provider
