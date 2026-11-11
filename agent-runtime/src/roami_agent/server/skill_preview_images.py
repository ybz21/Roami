"""Read bounded public GitHub illustrations without relying on the raw file domain."""

import asyncio
import base64
import binascii
import re
from urllib.parse import quote, unquote, urlsplit

from roami_agent.protocol.errors import DomainError

MAX_IMAGE_BYTES = 384_000
MAX_PREVIEW_BYTES = 768_000


def image_type(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


async def preview_images(text, fetch):
    urls = dict.fromkeys(re.findall(r"!\[[^\]\n]*\]\(\s*(https://[^\s)]+)", text))
    images, size = {}, 0
    deadline = asyncio.get_running_loop().time() + 6
    for url in list(urls)[:3]:
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        parts = unquote(parsed.path).strip("/").split("/")
        if (
            len(url) > 2000
            or parsed.netloc != "raw.githubusercontent.com"
            or parsed.query
            or parsed.fragment
            or len(parts) < 4
            or any(part in {"", ".", ".."} for part in parts)
            or not all(re.fullmatch(r"[a-zA-Z0-9][\w.-]*", part) for part in parts[:3])
        ):
            continue
        owner, repo, revision, *path = parts
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            async with asyncio.timeout(remaining):
                data = await fetch(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/"
                    + quote("/".join(path), safe="/"),
                    params={"ref": revision},
                    maximum=MAX_IMAGE_BYTES * 2,
                )
            if (
                data.get("type") != "file"
                or data.get("encoding") != "base64"
                or type(data.get("size")) is not int
                or not 0 < data["size"] <= MAX_IMAGE_BYTES
            ):
                continue
            raw = base64.b64decode("".join(data["content"].split()), validate=True)
            mime = image_type(raw)
            if not mime or len(raw) > MAX_IMAGE_BYTES or size + len(raw) > MAX_PREVIEW_BYTES:
                continue
            images[url] = f"data:{mime};base64," + base64.b64encode(raw).decode()
            size += len(raw)
        except (
            DomainError,
            KeyError,
            TypeError,
            ValueError,
            binascii.Error,
            AttributeError,
            TimeoutError,
        ):
            # Illustrations must not prevent reading or installing the skill itself.
            continue
    return images
