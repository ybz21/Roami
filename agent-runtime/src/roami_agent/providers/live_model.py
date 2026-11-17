"""Publish Main providers without closing requests that still hold a snapshot."""

import asyncio
from contextlib import contextmanager, suppress
from dataclasses import dataclass

from roami_agent.protocol.errors import ModelAdmissionRejected


@dataclass(eq=False)
class ProviderSnapshot:
    provider: object
    owned: bool = True
    readers: int = 0
    retired: bool = False
    closing: asyncio.Task | None = None


class LiveModel:
    def __init__(self, provider):
        self.snapshot = ProviderSnapshot(provider, owned=False)
        self.retired = set()

    @property
    def current(self):
        return self.snapshot.provider

    def __getattr__(self, name):
        return getattr(self.current, name)

    @contextmanager
    def lease(self):
        snapshot = self.snapshot
        snapshot.readers += 1
        try:
            yield snapshot.provider
        finally:
            snapshot.readers -= 1
            self._drain(snapshot)

    def _drain(self, snapshot):
        if not snapshot.retired or snapshot.readers or snapshot.closing:
            return
        if not snapshot.owned:
            self.retired.discard(snapshot)
            return

        async def close():
            try:
                with suppress(Exception):
                    await snapshot.provider.close()
            finally:
                self.retired.discard(snapshot)

        snapshot.closing = asyncio.create_task(close())

    async def replace(self, provider):
        previous = self.snapshot
        self.snapshot = ProviderSnapshot(provider)
        previous.retired = True
        self.retired.add(previous)
        self._drain(previous)
        if previous.closing:
            await asyncio.shield(previous.closing)

    async def stream(self, messages, tools):
        while True:
            with self.lease() as provider:
                emitted = False
                try:
                    async for part in provider.stream(messages, tools):
                        emitted = emitted or part.kind != "telemetry"
                        yield part
                    return
                except ModelAdmissionRejected as exc:
                    if (
                        exc.code != "MODEL_GATEWAY_ROUTE_CHANGED"
                        or provider is self.current
                        or emitted
                    ):
                        raise

    async def close(self):
        self.snapshot.retired = True
        self.retired.add(self.snapshot)
        for snapshot in tuple(self.retired):
            self._drain(snapshot)
        await asyncio.gather(
            *(snapshot.closing for snapshot in self.retired if snapshot.closing),
            return_exceptions=True,
        )
