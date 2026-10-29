"""Route configured model calls through the host's private Go accounting socket."""

import os

import httpx

from roami_agent.protocol.errors import ModelAdmissionRejected


class LocalGatewayTransport(httpx.AsyncBaseTransport):
    def __init__(self, socket, role):
        self.transport = httpx.AsyncHTTPTransport(uds=socket, retries=0)
        self.role = role

    async def handle_async_request(self, request):
        headers = dict(request.headers)
        headers["X-Roami-Model-Upstream"] = str(request.url)
        headers["X-Roami-Model-Role"] = self.role
        forwarded = httpx.Request(
            request.method,
            "http://roami-model/v1/chat/completions",
            headers=headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        response = await self.transport.handle_async_request(forwarded)
        code = response.headers.get("x-roami-model-error")
        if response.status_code >= 400 and code in {
            "MODEL_PROXY_DAILY_LIMIT",
            "MODEL_PROXY_USAGE_PENDING",
            "MODEL_PROXY_USAGE_UNKNOWN",
            "MODEL_GATEWAY_STORAGE_FAILED",
        }:
            await response.aclose()
            # Pending charges use the existing unsettled-cost recovery hint.
            if code == "MODEL_PROXY_USAGE_PENDING":
                code = "MODEL_PROXY_USAGE_UNKNOWN"
            raise ModelAdmissionRejected(code, response.status_code)
        return response

    async def aclose(self):
        await self.transport.aclose()


def local_gateway_client(role, timeout):
    socket = os.environ.get("ROAMI_MODEL_GATEWAY_SOCKET")
    if not socket:
        return None
    return httpx.AsyncClient(
        transport=LocalGatewayTransport(socket, role),
        timeout=httpx.Timeout(timeout or None, connect=10),
        follow_redirects=False,
    )
