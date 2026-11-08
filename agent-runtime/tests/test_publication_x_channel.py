import hashlib
import json

import httpx
import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.x_channel import XChannel

ACCOUNT = "12345"
VERSION = "a" * 64
BODY = b"fixture image bytes"
REFERENCE = {
    "sha256": hashlib.sha256(BODY).hexdigest(),
    "sizeBytes": len(BODY),
    "mimeType": "image/png",
}


class API:
    def __init__(self):
        self.calls, self.events = [], []
        self.account, self.protected, self.post_error = ACCOUNT, False, None
        self.text = "Exact frozen https://example.com"
        self.media = {"id": "456", "media_key": "3_456"}
        self.observed_media = ["3_456"]
        self.observed_author = ACCOUNT

    async def handle(self, request):
        self.calls.append((request.method, request.url.path))
        assert request.url.host == "api.x.com"
        assert request.headers["Authorization"] == "Bearer fixture-access"
        if request.url.path == "/2/users/me":
            return httpx.Response(
                200, json={"data": {"id": self.account, "protected": self.protected}}
            )
        if request.url.path == "/2/media/upload":
            assert BODY in await request.aread()
            return httpx.Response(200, json={"data": self.media})
        if request.method == "POST":
            assert self.events and self.events[-1]["phase"] == "post_submit"
            assert json.loads(await request.aread())["text"] == self.text
            if self.post_error:
                raise httpx.ReadTimeout("synthetic transport loss", request=request)
            return httpx.Response(201, json={"data": {"id": "789", "text": self.text}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "789",
                    "author_id": self.observed_author,
                    "text": "Exact frozen https://t.co/fixture",
                    "entities": {
                        "urls": [
                            {"url": "https://t.co/fixture", "expanded_url": "https://example.com"}
                        ]
                    },
                    "attachments": {"media_keys": self.observed_media},
                }
            },
        )

    async def journal(self, value):
        self.events.append(value)


async def test_exact_image_upload_create_and_public_readback_use_real_http_contract():
    api = API()
    async with httpx.AsyncClient(transport=httpx.MockTransport(api.handle)) as client:
        channel = XChannel(client, "fixture-access")
        media = await channel.upload_image(ACCOUNT, REFERENCE, BODY)
        created = await channel.create(
            ACCOUNT, "first-item", VERSION, api.text, [media], api.journal
        )
        assert created["state"] == "accepted"
        assert api.events[-1]["platformId"] == "789"
        assert api.events[-1]["requestSha256"] and "fixture-access" not in json.dumps(api.events)
        confirmed = await channel.confirm(ACCOUNT, "789", api.text, [media])
        assert confirmed["state"] == "public"
        assert confirmed["url"] == "https://x.com/i/web/status/789"
        assert sum(method == "POST" and path == "/2/tweets" for method, path in api.calls) == 1


@pytest.mark.parametrize(
    "fault", ["wrong_account", "private_account", "changed_image", "bad_media_id"]
)
async def test_wrong_account_or_changed_media_cannot_reach_post(fault):
    api = API()
    if fault == "wrong_account":
        api.account = "999"
    elif fault == "private_account":
        api.protected = True
    elif fault == "bad_media_id":
        api.media["id"] = "../../unrelated"
    async with httpx.AsyncClient(transport=httpx.MockTransport(api.handle)) as client:
        with pytest.raises(DomainError):
            await XChannel(client, "fixture-access").upload_image(
                ACCOUNT, REFERENCE, b"Changed" if fault == "changed_image" else BODY
            )
    assert ("POST", "/2/tweets") not in api.calls


async def test_host_journal_must_commit_before_post_and_refusal_does_not_send():
    api = API()

    async def refuse(value):
        raise DomainError("PUBLICATION_DURABLE_ATTEMPT_REQUIRED", 409)

    async with httpx.AsyncClient(transport=httpx.MockTransport(api.handle)) as client:
        with pytest.raises(DomainError):
            await XChannel(client, "fixture-access").create(
                ACCOUNT, "first", VERSION, api.text, [], refuse
            )
    assert ("POST", "/2/tweets") not in api.calls


async def test_transport_loss_keeps_submit_receipt_and_never_replays_post():
    api = API()
    api.post_error = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(api.handle)) as client:
        with pytest.raises(DomainError, match="PUBLICATION_NETWORK_OUTCOME_UNKNOWN"):
            await XChannel(client, "fixture-access").create(
                ACCOUNT, "first", VERSION, api.text, [], api.journal
            )
    assert [e["phase"] for e in api.events] == ["post_submit"]
    assert api.calls.count(("POST", "/2/tweets")) == 1


@pytest.mark.parametrize("fault", ["author", "media"])
async def test_readback_requires_same_account_and_media(fault):
    api = API()
    if fault == "author":
        api.observed_author = "999"
    else:
        api.observed_media = ["3_999"]
    media = [
        {"id": "456", "mediaKey": "3_456", "accountId": ACCOUNT, "sha256": REFERENCE["sha256"]}
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(api.handle)) as client:
        with pytest.raises(DomainError):
            await XChannel(client, "fixture-access").confirm(ACCOUNT, "789", api.text, media)
    assert not any(method == "POST" for method, path in api.calls)


async def test_redirect_never_sends_account_token_to_another_origin():
    calls = []

    async def redirected(request):
        calls.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://outside.invalid/collect"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(redirected), follow_redirects=True
    ) as client:
        with pytest.raises(DomainError, match="PUBLICATION_CHANNEL_READ_FAILED"):
            await XChannel(client, "fixture-access").identity(ACCOUNT)
    assert calls == ["api.x.com"]


async def test_unavailable_identity_read_does_not_journal_or_submit_a_post():
    api = API()

    async def offline(request):
        api.calls.append((request.method, request.url.path))
        raise httpx.ConnectError("synthetic offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as client:
        with pytest.raises(DomainError, match="PUBLICATION_CHANNEL_READ_FAILED"):
            await XChannel(client, "fixture-access").create(
                ACCOUNT, "first", VERSION, api.text, [], api.journal
            )
    assert api.events == [] and api.calls == [("GET", "/2/users/me")]


async def test_success_status_without_post_id_stays_unconfirmed_without_replay():
    api = API()

    async def missing_id(request):
        if request.method == "POST":
            api.calls.append((request.method, request.url.path))
            return httpx.Response(201, json={"data": {"text": api.text}})
        return await api.handle(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(missing_id)) as client:
        with pytest.raises(DomainError, match="PUBLICATION_RECEIPT_UNCONFIRMED"):
            await XChannel(client, "fixture-access").create(
                ACCOUNT, "first", VERSION, api.text, [], api.journal
            )
    assert api.calls.count(("POST", "/2/tweets")) == 1
    assert [e["phase"] for e in api.events] == ["post_submit"]


async def test_lost_receipt_journal_ack_never_causes_transport_to_submit_again():
    api = API()

    async def lost_ack(value):
        if value["phase"] == "post_created":
            raise OSError("synthetic receipt write failure")
        await api.journal(value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(api.handle)) as client:
        with pytest.raises(OSError):
            await XChannel(client, "fixture-access").create(
                ACCOUNT, "first", VERSION, api.text, [], lost_ack
            )
    assert api.calls.count(("POST", "/2/tweets")) == 1
    assert [e["phase"] for e in api.events] == ["post_submit"]


async def test_partial_create_response_preserves_known_id_before_readback():
    api = API()

    async def partial(request):
        if request.method == "POST":
            assert api.events[-1]["phase"] == "post_submit"
            return httpx.Response(
                201,
                json={
                    "data": {"id": "789"},
                    "errors": [{"detail": "unrelated optional field unavailable"}],
                },
            )
        return await api.handle(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(partial)) as client:
        result = await XChannel(client, "fixture-access").create(
            ACCOUNT, "first", VERSION, api.text, [], api.journal
        )
    assert result["state"] == "accepted" and api.events[-1]["platformId"] == "789"
    assert api.events[-1]["responseHadErrors"] is True
