"""Local HTTP transport proxy: forward streaming bytes and durably account each attempt."""

import asyncio
import json
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from decimal import Decimal

import httpx

from roami_agent.providers.model_billing import ModelBilling, proxy_configuration, usage_counts
from roami_agent.providers.upstream_costs import upstream_charge

model_proxy_context = ContextVar("model_proxy_context", default=None)


@contextmanager
def model_accounting(proxy):
    token = model_proxy_context.set(proxy)
    try:
        yield
    finally:
        model_proxy_context.reset(token)


class ModelProxy:
    def __init__(self, database, configuration, timezone):
        self.billing = ModelBilling(database, configuration, timezone)
        self.admission = asyncio.Lock()
        self.recovery = asyncio.Lock()

    def attach(self, provider, role):
        if getattr(provider, "_roami_model_proxy", None) is self:
            return provider
        upstream = provider.client
        provider.client = httpx.AsyncClient(
            transport=ProxyTransport(self, upstream, role, provider.model),
            timeout=upstream.timeout,
            follow_redirects=False,
        )
        provider._roami_model_proxy = self
        return provider

    async def ready(self):
        async with self.recovery:
            await self.billing.recover()

    @asynccontextmanager
    async def external_turn(self, role, model):
        await self.ready()
        limited = proxy_configuration(self.billing.configuration())["dailyLimit"] is not None
        held, call_id = False, None
        receipt = {"sent": False, "counts": None}
        error = None
        try:
            if limited:
                await self.admission.acquire()
                held = True
            admission = asyncio.create_task(self.billing.admit(role, model))
            try:
                call_id = await asyncio.shield(admission)
            except asyncio.CancelledError:
                call_id = await admission
                raise
            yield receipt
        except BaseException as exc:
            error = getattr(exc, "code", "MODEL_PROXY_EXTERNAL_FAILED")
            raise
        finally:
            try:
                if call_id is not None:
                    await finish(
                        self.billing.settle(
                            call_id,
                            receipt["counts"],
                            failed=error is not None and receipt["counts"] is None,
                            not_sent=not receipt["sent"],
                            error=error,
                        )
                    )
            finally:
                if held:
                    self.admission.release()


async def finish(operation):
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class ProxyTransport(httpx.AsyncBaseTransport):
    def __init__(self, proxy, upstream, role, model, *, on_attempt=None):
        self.proxy, self.upstream, self.role, self.model = proxy, upstream, role, model
        self.on_attempt = on_attempt

    async def handle_async_request(self, request):
        await self.proxy.ready()
        limited = proxy_configuration(self.proxy.billing.configuration())["dailyLimit"] is not None
        held = False
        call_id = None
        sent = False
        try:
            if limited:
                await self.proxy.admission.acquire()
                held = True
            admission = asyncio.create_task(self.proxy.billing.admit(self.role, self.model))
            try:
                call_id = await asyncio.shield(admission)
            except asyncio.CancelledError:
                call_id = await admission
                raise
            sent = True
            if self.on_attempt is not None:
                self.on_attempt()
            response = await self.upstream.send(request, stream=True, follow_redirects=False)
            stream = MeteredStream(response, self.proxy, call_id, request.url, held)
            held = False
            headers = response.headers.copy()
            # The inner client decodes compression before metering; do not decode twice.
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            return httpx.Response(
                response.status_code,
                headers=headers,
                stream=stream,
                extensions=response.extensions,
            )
        except BaseException as error:
            if call_id is not None:
                await finish(
                    self.proxy.billing.settle(
                        call_id,
                        None,
                        failed=True,
                        not_sent=not sent
                        or isinstance(
                            error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
                        ),
                        error="MODEL_PROXY_TRANSPORT_FAILED",
                    )
                )
            raise
        finally:
            if held:
                self.proxy.admission.release()

    async def aclose(self):
        await self.upstream.aclose()


class MeteredStream(httpx.AsyncByteStream):
    def __init__(self, response, proxy, call_id, endpoint, held):
        self.response, self.proxy, self.call_id, self.endpoint = response, proxy, call_id, endpoint
        self.held, self.closed = held, False
        self.buffer = bytearray()
        self.counts = None
        self.charge = None
        self.invalid = False
        self.complete = False
        self.sse = "text/event-stream" in response.headers.get("content-type", "")
        self.success = 200 <= response.status_code < 300

    def observe(self, raw):
        if raw == b"[DONE]":
            self.complete = True
            return
        if len(raw) > 1_000_000:
            self.invalid = True
            return
        try:
            value = json.loads(raw, parse_float=Decimal)
        except (ValueError, UnicodeError):
            self.invalid = True
            return
        terminal = {
            "response.completed": "completed",
            "response.failed": "failed",
            "response.incomplete": "incomplete",
        }
        if isinstance(value, dict) and value.get("type") in terminal:
            response = value.get("response")
            if isinstance(response, dict) and response.get("status") == terminal[value["type"]]:
                self.complete = True
                value = response
        if isinstance(value, dict) and value.get("usage") is not None:
            self.counts = usage_counts(value["usage"])
            self.charge = upstream_charge(value["usage"], self.endpoint)

    async def __aiter__(self):
        try:
            async for chunk in self.response.aiter_bytes():
                if self.success:
                    self.buffer.extend(chunk)
                    if self.sse:
                        while b"\n" in self.buffer:
                            line, _, remaining = self.buffer.partition(b"\n")
                            self.buffer = bytearray(remaining)
                            if line.startswith(b"data:"):
                                self.observe(line[5:].strip())
                    if len(self.buffer) > 1_000_000:
                        self.buffer.clear()
                        self.invalid = True
                yield chunk
            if self.success:
                if not self.sse:
                    self.observe(self.buffer)
                    self.complete = True
                elif self.buffer.startswith(b"data:"):
                    self.observe(self.buffer[5:].strip())
        finally:
            await self.aclose()

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        try:
            await finish(self.response.aclose())
        finally:
            try:
                await finish(
                    self.proxy.billing.settle(
                        self.call_id,
                        None if self.invalid or not self.complete else self.counts,
                        charge=self.charge if self.complete and not self.invalid else None,
                        failed=not self.success,
                        error=None
                        if self.success
                        else "MODEL_HTTP_" + str(self.response.status_code),
                    )
                )
            finally:
                if self.held:
                    self.proxy.admission.release()
