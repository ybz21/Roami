import hashlib
import io
import json

import httpx
import pytest
from PIL import Image

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.x_public import XPublic


def picture(color, fmt):
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(stream, format=fmt)
    return stream.getvalue()


@pytest.mark.parametrize(
    "fault", [None, "author", "body", "alt", "photo", "image", "range", "redirect", "url", "source"]
)
async def test_native_x_public_readback_matches_frozen_bytes_without_oauth(fault):
    source = picture("red", "PNG")
    frozen = {"sha256": hashlib.sha256(source).hexdigest()}
    raw_text = "🙂 Frozen https://t.co/example"
    calls = []

    def read(request):
        calls.append(request)
        assert request.method == "GET" and "authorization" not in request.headers
        if request.url.host == "pbs.twimg.com":
            return httpx.Response(
                200, content=picture("blue" if fault == "image" else "red", "JPEG")
            )
        assert request.url.host == "cdn.syndication.twimg.com"
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://outside.invalid/"})
        return httpx.Response(
            200,
            json={
                "id_str": "2119534503328874878",
                "user": {"id_str": "wrong" if fault == "author" else "2072236826807705600"},
                "text": raw_text,
                "display_text_range": [
                    1 if fault == "range" else 0,
                    len(raw_text.encode("utf-16-le")) // 2,
                ],
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/example",
                            "expanded_url": "https://github.com/ybz21/Roami",
                        }
                    ]
                },
                "mediaDetails": [
                    {
                        "type": "video" if fault == "photo" else "photo",
                        "ext_alt_text": "wrong" if fault == "alt" else "Frozen ALT",
                        "media_url_https": "https://outside.invalid/image.jpg"
                        if fault == "url"
                        else "https://pbs.twimg.com/media/frozen.jpg",
                    }
                ],
            },
        )

    async def image(reference):
        assert reference == frozen
        return b"changed" if fault == "source" else source

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(read), follow_redirects=True
    ) as client:
        service = XPublic(client, image)
        args = (
            "2072236826807705600",
            "2119534503328874878",
            "changed" if fault == "body" else "🙂 Frozen https://github.com/ybz21/Roami\n",
            ["Frozen ALT\n"],
            [frozen],
        )
        if fault:
            with pytest.raises(DomainError):
                await service.confirm(*args)
        else:
            fact = await service.confirm(*args)
            assert fact["accountId"] == "2072236826807705600"
            assert fact["publicImageBinaryEqualityAsserted"] is False
            assert fact["photos"][0]["rgbRMSE"] < 10
        assert len(calls) == (2 if fault in {None, "image"} else 1)
        with pytest.raises(DomainError, match="INVALID_PUBLICATION_IDENTITY"):
            await service.confirm(2072236826807705600, *args[1:])


@pytest.mark.parametrize(
    "provider_prefix,expected_prefix,expanded_url,rejected",
    [
        (
            "Capabilities &gt; Agents &amp; review &lt; next",
            "Capabilities > Agents & review < next",
            "https://example.test/?a=1&b=2",
            False,
        ),
        (
            "Type &amp;gt; literally",
            "Type &gt; literally",
            "https://example.test/?a=1&b=2",
            False,
        ),
        ("Open", "Open", "https://example.test/?token=&amp;", False),
        ("Type &amp;gt; literally", "Type > literally", "https://example.test/", True),
    ],
)
async def test_native_x_decodes_provider_text_once_before_expanding_urls(
    provider_prefix, expected_prefix, expanded_url, rejected
):
    raw_text = provider_prefix + " https://t.co/example"
    calls = []

    def read(request):
        calls.append(request)
        assert request.method == "GET" and "authorization" not in request.headers
        assert request.url.host == "cdn.syndication.twimg.com"
        return httpx.Response(
            200,
            json={
                "id_str": "2119579388375425486",
                "user": {"id_str": "2072236826807705600"},
                "text": raw_text,
                "display_text_range": [0, len(raw_text.encode("utf-16-le")) // 2],
                "entities": {
                    "urls": [{"url": "https://t.co/example", "expanded_url": expanded_url}]
                },
                "mediaDetails": [],
            },
        )

    async def image(reference):
        raise AssertionError("No media is selected in this text fixture")

    async with httpx.AsyncClient(transport=httpx.MockTransport(read)) as client:
        service = XPublic(client, image)
        args = (
            "2072236826807705600",
            "2119579388375425486",
            expected_prefix + " " + expanded_url,
            [],
            [],
        )
        if rejected:
            with pytest.raises(DomainError, match="PUBLICATION_CONTENT_UNCONFIRMED"):
                await service.confirm(*args)
        else:
            fact = await service.confirm(*args)
            assert fact["state"] == "public"
            assert json.loads(fact["rawResponse"])["text"] == raw_text
    assert len(calls) == 1
