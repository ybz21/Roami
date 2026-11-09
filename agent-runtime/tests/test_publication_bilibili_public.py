import copy
import hashlib

import httpx
import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.bilibili_public import BilibiliPublic


@pytest.mark.parametrize(
    "fault",
    [None, "author", "title", "description", "cid", "pending", "missing", "redirect", "malformed"],
)
async def test_native_bili_readback_checks_known_content_without_any_write(fault):
    data = {
        "bvid": "BV1cpWp6FE8f",
        "state": 0,
        "owner": {"mid": 243999833},
        "title": "Frozen title",
        "desc": "Frozen description",
        "cid": 43447814557,
    }
    original = copy.deepcopy(data)
    calls = []

    def read(request):
        calls.append(request)
        assert request.method == "GET"
        assert str(request.url) == (
            "https://api.bilibili.com/x/web-interface/view?bvid=BV1cpWp6FE8f"
        )
        assert "authorization" not in request.headers
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://outside.invalid/"})
        if fault == "malformed":
            return httpx.Response(200, text="<html>rate limit</html>")
        if fault == "author":
            data["owner"]["mid"] = 123
        elif fault in {"title", "description", "cid"}:
            data[{"title": "title", "description": "desc", "cid": "cid"}[fault]] = "changed"
        elif fault == "pending":
            data["state"] = -4
        return httpx.Response(200, json={"code": -404 if fault == "missing" else 0, "data": data})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(read), follow_redirects=True
    ) as client:
        service = BilibiliPublic(client)
        args = (
            "243999833",
            original["bvid"],
            original["title"] + "\n",
            original["desc"] + "\n",
            str(original["cid"]),
        )
        if fault:
            with pytest.raises(DomainError):
                await service.confirm(*args)
        else:
            fact = await service.confirm(*args)
            assert fact["state"] == "public"
            assert (
                hashlib.sha256(fact["rawResponse"].encode()).hexdigest()
                == fact["rawResponseSha256"]
            )
        assert len(calls) == 1
        with pytest.raises(DomainError, match="INVALID_PUBLICATION_IDENTITY"):
            await service.confirm("243999833", "https://outside.invalid/", "title", "body", "1")
        assert len(calls) == 1
