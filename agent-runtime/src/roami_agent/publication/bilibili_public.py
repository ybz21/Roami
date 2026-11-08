"""Read public Bilibili facts for a known native submission; never publish."""

import hashlib
import re

import httpx

from roami_agent.protocol.errors import DomainError


class BilibiliPublic:
    def __init__(self, client):
        self.client = client

    async def readback(self, context, prepared, platform_id):
        if context.get("channel") != "bilibili":
            raise DomainError("PUBLICATION_CHANNEL_UNAVAILABLE", 409)
        content = prepared.get("content")
        platform_media = prepared.get("platformMedia")
        if not isinstance(content, dict) or not isinstance(platform_media, dict):
            raise DomainError("PUBLICATION_SUBMISSION_SCOPE_CONFLICT", 409)
        return await self.confirm(
            context["accountId"],
            platform_id,
            content.get("title"),
            content.get("description"),
            platform_media.get("cid"),
        )

    async def confirm(self, account, bvid, title, description, cid):
        if (
            not isinstance(account, str)
            or not re.fullmatch(r"[1-9][0-9]{0,29}", account)
            or not isinstance(bvid, str)
            or not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid)
            or not isinstance(cid, str)
            or not re.fullmatch(r"[1-9][0-9]{0,29}", cid)
            or not isinstance(title, str)
            or not title.strip()
            or not isinstance(description, str)
        ):
            raise DomainError("INVALID_PUBLICATION_IDENTITY")
        try:
            response = await self.client.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise DomainError("PUBLICATION_CHANNEL_READ_FAILED", 409) from exc
        if response.status_code != 200:
            raise DomainError("PUBLICATION_CHANNEL_READ_FAILED", 409)
        try:
            value = response.json()
            data = value["data"]
            if value["code"] != 0 or not isinstance(data, dict) or data["state"] != 0:
                raise ValueError("not public")
            if data["bvid"] != bvid or str(data["owner"]["mid"]) != account:
                raise DomainError("PUBLICATION_RECEIPT_SCOPE_CONFLICT", 403)
            if (
                data["title"] != title.rstrip("\n")
                or data["desc"].rstrip("\n") != description.rstrip("\n")
                or str(data["cid"]) != cid
            ):
                raise DomainError("PUBLICATION_CONTENT_UNCONFIRMED", 409)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise DomainError("PUBLICATION_RECEIPT_UNCONFIRMED", 409) from exc
        return {
            "state": "public",
            "channel": "bilibili",
            "platformId": bvid,
            "accountId": account,
            "cid": cid,
            "url": "https://www.bilibili.com/video/" + bvid + "/",
            "rawResponseSha256": hashlib.sha256(response.content).hexdigest(),
            "rawResponse": response.text,
            "contentComparison": "title-description-terminal-lf-and-cid",
        }
