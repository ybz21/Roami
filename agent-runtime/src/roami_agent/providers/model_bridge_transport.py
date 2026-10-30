"""Only the host's private model relay may supply relayed request receipts."""

import httpx

from roami_agent.providers.request_receipts import BRIDGE_EXTENSION


class PrivateModelBridgeTransport(httpx.AsyncHTTPTransport):
    def __init__(self, socket):
        super().__init__(uds=socket, retries=0)

    async def handle_async_request(self, request):
        response = await super().handle_async_request(request)
        response.extensions[BRIDGE_EXTENSION] = True
        return response
