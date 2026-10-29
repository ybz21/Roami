"""Resolve automatic capacity identically for service and standalone runtimes."""

import asyncio
from dataclasses import replace

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.model_catalog import fetch_catalog


async def resolve_model_capacity(settings, *, fetch=None):
    fetch = fetch or fetch_catalog

    async def resolve(role):
        route = settings.route(role)
        if route.context_window is not None or not route.endpoint or not route.name:
            return route
        try:
            catalog = await fetch(route.endpoint, settings.credentials(role))
        except DomainError:
            return route
        return replace(route, context_window=catalog.get(route.name))

    main, worker = await asyncio.gather(resolve("main"), resolve("worker"))
    return replace(settings, context_window=main.context_window, worker_route=worker)
