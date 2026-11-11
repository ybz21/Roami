"""Read bounded public GitHub illustrations without relying on the raw file domain."""

import asyncio
import base64
import binascii
import re
from urllib.parse import quote, unquote, urlsplit

from roami_agent.protocol.errors import DomainError

MAX_IMAGE_BYTES = 384_000
MAX_PREVIEW_BYTES = 768_000
PREVIEW_TIMEOUT = 6


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


async def read_image(url, fetch):
    try:
        parsed = urlsplit(url)
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
            return None
        owner, repo, revision, *path = parts
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
            return None
        raw = base64.b64decode("".join(data["content"].split()), validate=True)
        mime = image_type(raw)
        if mime and len(raw) <= MAX_IMAGE_BYTES:
            return url, mime, raw
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
        pass
    return None


async def preview_images(text, fetch):
    urls = list(dict.fromkeys(re.findall(r"!\[[^\]\n]*\]\(\s*(https://[^\s)]+)", text)))[:3]
    if not urls:
        return {}
    tasks = [asyncio.create_task(read_image(url, fetch)) for url in urls]
    try:
        await asyncio.wait(tasks, timeout=PREVIEW_TIMEOUT)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    images, size = {}, 0
    for task in tasks:
        if task.cancelled() or not (result := task.result()):
            continue
        url, mime, raw = result
        if size + len(raw) <= MAX_PREVIEW_BYTES:
            images[url] = f"data:{mime};base64," + base64.b64encode(raw).decode()
            size += len(raw)
    return images
