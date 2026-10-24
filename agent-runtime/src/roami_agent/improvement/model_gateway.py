"""Private Unix-socket model bridge; credentials and authoritative usage stay on the host."""

import asyncio
import json
import re

from roami_agent.protocol.errors import DomainError


class ModelGateway:
    def __init__(self, socket, models):
        self.socket, self.models = socket, models
        self.server = None
        self.clients = set()
        self.errors = []

    async def __aenter__(self):
        self.server = await asyncio.start_unix_server(
            self.handle, path=str(self.socket), limit=2_100_000
        )
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()
        clients = list(self.clients)
        for task in clients:
            task.cancel()
        await asyncio.gather(*clients, return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.clients.add(task)
        sent = False
        try:
            async with asyncio.timeout(20):
                headers = (await reader.readuntil(b"\r\n\r\n")).decode("latin1")
                method, path, _ = headers.split("\r\n", 1)[0].split(" ")
                if method == "GET" and path.endswith("/models"):
                    writer.write(
                        b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{"data":[]}'
                    )
                    await writer.drain()
                    return
                match = re.fullmatch(r"/v1/(main|worker|memory)/chat/completions", path)
                if method != "POST" or not match:
                    raise DomainError("RSI_GATEWAY_ROUTE")
                length = re.search(r"(?im)^Content-Length:\s*(\d+)\s*$", headers)
                if not length or not 0 < int(length[1]) <= 2_000_000:
                    raise DomainError("RSI_GATEWAY_SIZE")
                body = json.loads(await reader.readexactly(int(length[1])))
            if not isinstance(body.get("messages"), list) or not isinstance(
                body.get("tools", []), list
            ):
                raise DomainError("RSI_GATEWAY_INPUT")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
            )
            sent = True
            index = 0
            async for event in self.models[match[1]].stream(
                body["messages"], body.get("tools", [])
            ):
                if event.kind == "text":
                    data = {"choices": [{"index": 0, "delta": {"content": event.value}}]}
                elif event.kind == "tool":
                    data = {
                        "choices": [
                            {"index": 0, "delta": {"tool_calls": [{"index": index, **event.value}]}}
                        ]
                    }
                    index += 1
                elif event.kind == "usage":
                    usage = event.value
                    data = {
                        "choices": [],
                        "usage": {
                            "prompt_tokens": usage.get("inputTokens"),
                            "completion_tokens": usage.get("outputTokens"),
                            "prompt_tokens_details": {
                                "cached_tokens": usage.get("cacheReadTokens")
                            },
                        },
                    }
                else:
                    continue
                writer.write(b"data: " + json.dumps(data, ensure_ascii=False).encode() + b"\n\n")
                await writer.drain()
            writer.write(
                b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            )
            await writer.drain()
        except (
            DomainError,
            OSError,
            ValueError,
            asyncio.IncompleteReadError,
            TimeoutError,
        ) as error:
            code = error.code if isinstance(error, DomainError) else "RSI_GATEWAY_FAILED"
            self.errors.append(code)
            try:
                data = json.dumps({"error": {"code": code}}).encode()
                writer.write(
                    (b"data: " + data + b"\n\n")
                    if sent
                    else b"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n"
                    + data
                )
                await writer.drain()
            except OSError:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            finally:
                self.clients.discard(task)
