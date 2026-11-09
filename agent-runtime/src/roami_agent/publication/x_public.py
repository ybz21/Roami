"""Read native X posts and compare public photo pixels with frozen images."""

import hashlib
import html
import io
import math
import re
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageChops, ImageStat

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.x_channel import numeric


class XPublic:
    def __init__(self, client, source_image):
        self.client, self.source_image = client, source_image

    async def get(self, url, **kwargs):
        try:
            response = await self.client.get(url, follow_redirects=False, **kwargs)
        except httpx.HTTPError as exc:
            raise DomainError("PUBLICATION_CHANNEL_READ_FAILED", 409) from exc
        if response.status_code != 200:
            raise DomainError("PUBLICATION_CHANNEL_READ_FAILED", 409)
        return response

    async def readback(self, context, prepared, platform_id):
        if context.get("channel") != "x":
            raise DomainError("PUBLICATION_CHANNEL_UNAVAILABLE", 409)
        content = prepared.get("content")
        if not isinstance(content, dict):
            raise DomainError("PUBLICATION_SUBMISSION_SCOPE_CONFLICT", 409)
        return await self.confirm(
            context["accountId"],
            platform_id,
            content.get("text"),
            content.get("imageAlts"),
            prepared.get("media"),
        )

    async def confirm(self, account, post_id, text, alts, images):
        if not numeric(account) or not numeric(post_id):
            raise DomainError("INVALID_PUBLICATION_IDENTITY")
        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(alts, list)
            or not all(isinstance(alt, str) for alt in alts)
            or not isinstance(images, list)
            or len(images) != len(alts)
            or len(images) > 4
        ):
            raise DomainError("INVALID_PUBLICATION_CONTENT")
        response = await self.get(
            "https://cdn.syndication.twimg.com/tweet-result",
            params={"id": post_id, "lang": "en", "token": "0"},
        )
        try:
            value = response.json()
            if value["id_str"] != post_id or value["user"]["id_str"] != account:
                raise DomainError("PUBLICATION_RECEIPT_SCOPE_CONFLICT", 403)
            start, end = value["display_text_range"]
            body = value["text"].encode("utf-16-le")
            if (
                type(start) is not int
                or type(end) is not int
                or not 0 <= start <= end <= len(body) // 2
            ):
                raise ValueError("invalid display range")
            observed = html.unescape(body[start * 2 : end * 2].decode("utf-16-le"))
            for url in value["entities"].get("urls", []):
                observed = observed.replace(url["url"], url["expanded_url"])
            media = value.get("mediaDetails", [])
            if observed != text.rstrip("\n") or len(media) != len(images):
                raise DomainError("PUBLICATION_CONTENT_UNCONFIRMED", 409)
            if any(
                item["type"] != "photo" or item.get("ext_alt_text", "") != alt.rstrip("\n")
                for item, alt in zip(media, alts, strict=True)
            ):
                raise DomainError("PUBLICATION_CONTENT_UNCONFIRMED", 409)
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
            raise DomainError("PUBLICATION_RECEIPT_UNCONFIRMED", 409) from exc
        photo_proofs = []
        for item, reference in zip(media, images, strict=True):
            url = item.get("media_url_https", "")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "pbs.twimg.com"
                or parsed.query
                or parsed.fragment
                or not re.fullmatch(r"/media/[A-Za-z0-9_-]+\.(jpg|png|webp)", parsed.path)
            ):
                raise DomainError("PUBLICATION_MEDIA_SCOPE_CONFLICT", 403)
            source = await self.source_image(reference)
            if (
                not isinstance(source, bytes)
                or not isinstance(reference, dict)
                or (hashlib.sha256(source).hexdigest() != reference.get("sha256"))
            ):
                raise DomainError("PUBLICATION_MEDIA_INTEGRITY_FAILED", 409)
            public = await self.get(url, params={"name": "orig"})
            proof = self.compare_images(source, public.content)
            photo_proofs.append(
                {
                    **proof,
                    "sourceSha256": reference["sha256"],
                    "publicSha256": hashlib.sha256(public.content).hexdigest(),
                }
            )
        return {
            "state": "public",
            "channel": "x",
            "platformId": post_id,
            "accountId": account,
            "url": "https://x.com/i/web/status/" + post_id,
            "rawResponse": response.text,
            "rawResponseSha256": hashlib.sha256(response.content).hexdigest(),
            "photos": photo_proofs,
            "publicImageBinaryEqualityAsserted": False,
        }

    @staticmethod
    def compare_images(source, public):
        if not source or not public or max(len(source), len(public)) > 5 * 1024 * 1024:
            raise DomainError("PUBLICATION_MEDIA_INTEGRITY_FAILED", 409)
        try:
            with Image.open(io.BytesIO(source)) as a, Image.open(io.BytesIO(public)) as b:
                if a.size != b.size or max(a.size) > 4096:
                    raise ValueError("dimensions")
                stats = ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB")))
                rmse = math.sqrt(sum(value * value for value in stats.rms) / 3)
                mae = sum(stats.mean) / 3
                if rmse >= 10 or mae >= 4:
                    raise ValueError("pixels")
                return {
                    "width": a.width,
                    "height": a.height,
                    "rgbRMSE": rmse,
                    "meanAbsoluteChannelError": mae,
                }
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise DomainError("PUBLICATION_MEDIA_INTEGRITY_FAILED", 409) from exc
