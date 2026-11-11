"""Stream read-only preview modules; issue an install receipt only after the bundle is complete."""

import asyncio
import json

from roami_agent.protocol.errors import DomainError


async def preview_stream(markets, owner, payload):
    queue = asyncio.Queue()

    async def prepare():
        try:
            data = await markets.installations.prepare(
                owner, payload, include_content=True, on_progress=queue.put_nowait
            )
            queue.put_nowait({"type": "ready", "data": data})
        # A started stream must terminate with a readable error frame.
        except Exception as exc:  # noqa: BLE001
            code = exc.code if isinstance(exc, DomainError) else "MARKET_UNAVAILABLE"
            queue.put_nowait({"type": "error", "error": {"code": code}})

    task = asyncio.create_task(prepare())
    try:
        yield json.dumps({"type": "loading"}) + "\n"
        while True:
            event = await queue.get()
            yield json.dumps(event, ensure_ascii=False) + "\n"
            if event["type"] in {"ready", "error"}:
                break
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
