"""DONE terminates model output while bounded EOF cleanup preserves HTTP pooling."""

import asyncio
import time

import httpx

from roami_agent.providers.chat_completions import ChatCompletions

BODY = b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'


async def test_terminal_http_chunk_is_consumed_so_sequential_turns_reuse_one_connection():
    connections, requests, writers = 0, 0, []

    async def handle(reader, writer):
        nonlocal connections, requests
        connections += 1
        writers.append(writer)
        try:
            while True:
                header = await reader.readuntil(b"\r\n\r\n")
                length = next(
                    int(line.split(b":", 1)[1])
                    for line in header.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                )
                await reader.readexactly(length)
                requests += 1
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n"
                    + f"{len(BODY):x}\r\n".encode()
                    + BODY
                    + b"\r\n"
                )
                await writer.drain()
                await asyncio.sleep(0.01)
                writer.write(b"0\r\n\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    model = ChatCompletions(
        f"http://127.0.0.1:{port}/v1", "fixture", client=httpx.AsyncClient(trust_env=False)
    )
    try:
        for _ in range(3):
            parts = [
                part async for part in model.stream([{"role": "user", "content": "Question"}], [])
            ]
            assert [part.value for part in parts if part.kind == "text"] == ["ok"]
        assert requests == 3 and connections == 1
    finally:
        await model.close()
        server.close()
        await server.wait_closed()
        for writer in writers:
            writer.close()
            await writer.wait_closed()


async def test_terminal_cleanup_is_bounded_if_provider_never_ends_http_body():
    class OpenStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield BODY
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    stream = OpenStream()

    async def handle(request):
        return httpx.Response(200, stream=stream)

    model = ChatCompletions(
        "https://provider.invalid/v1",
        "fixture",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        timeout=2,
    )
    started = time.monotonic()
    try:
        parts = [part async for part in model.stream([{"role": "user", "content": "Question"}], [])]
        assert [part.value for part in parts if part.kind == "text"] == ["ok"]
        assert time.monotonic() - started < 0.5 and stream.closed
    finally:
        await model.close()
