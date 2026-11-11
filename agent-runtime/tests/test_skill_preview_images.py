import asyncio
import base64

import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.server import skill_preview_images
from roami_agent.server.skill_preview_images import MAX_IMAGE_BYTES, preview_images

URL = "https://raw.githubusercontent.com/publisher/skills/main/assets/hero.png"
PNG = b"\x89PNG\r\n\x1a\nillustration"


def image_response(raw):
    return {
        "type": "file",
        "size": len(raw),
        "encoding": "base64",
        "content": base64.b64encode(raw).decode(),
    }


@pytest.mark.asyncio
async def test_github_illustrations_use_contents_api_and_deduplicate_urls():
    seen = []

    async def fetch(url, **kwargs):
        seen.append(url)
        assert url == "https://api.github.com/repos/publisher/skills/contents/assets/hero.png"
        assert kwargs == {"params": {"ref": "main"}, "maximum": MAX_IMAGE_BYTES * 2}
        return image_response(PNG)

    images = await preview_images(
        f"[![Effect]({URL})](https://example.com)\n![Again]({URL})", fetch
    )
    assert images == {URL: "data:image/png;base64," + base64.b64encode(PNG).decode()}
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/image.png",
        "https://[invalid/image.png",
        "https://raw.githubusercontent.com/o/r/main/" + "x" * 2000 + ".png",
        "https://raw.githubusercontent.com.evil.test/o/r/main/a.png",
        "https://raw.githubusercontent.com/o/r/main/../a.png",
        "https://raw.githubusercontent.com/o/r/main/%2e%2e/a.png",
        "https://raw.githubusercontent.com/o/r/main/a.png?token=secret",
    ],
)
async def test_preview_never_fetches_unapproved_destinations(url):
    async def fetch(*args, **kwargs):
        pytest.fail("Unexpected image request")

    assert await preview_images(f"![Effect]({url})", fetch) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", [b'<svg onload="alert(1)">', b"<html>error</html>", b"x" * (MAX_IMAGE_BYTES + 1)]
)
async def test_preview_rejects_active_non_image_and_oversized_files(raw):
    async def fetch(*args, **kwargs):
        return image_response(raw)

    assert await preview_images(f"![Effect]({URL})", fetch) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [DomainError("MARKET_RATE_LIMITED", 429), TimeoutError()])
async def test_unavailable_illustrations_do_not_block_skill_details(error):
    async def fetch(*args, **kwargs):
        raise error

    assert await preview_images(f"![Effect]({URL})", fetch) == {}


@pytest.mark.asyncio
async def test_preview_image_count_and_total_size_are_bounded():
    seen = []
    raw = PNG + b"x" * (MAX_IMAGE_BYTES - len(PNG))

    async def fetch(url, **kwargs):
        seen.append(url)
        return image_response(raw)

    text = "\n".join(
        f"![Effect](https://raw.githubusercontent.com/o/r/main/{index}.png)" for index in range(5)
    )
    images = await preview_images(text, fetch)
    assert len(seen) == 3 and len(images) == 2


async def test_illustrations_load_concurrently():
    started, all_started = [], asyncio.Event()

    async def fetch(url, **kwargs):
        started.append(url)
        if len(started) == 3:
            all_started.set()
        await all_started.wait()
        return image_response(PNG)

    text = "\n".join(
        f"![Effect](https://raw.githubusercontent.com/o/r/main/{index}.png)" for index in range(3)
    )
    images = await asyncio.wait_for(preview_images(text, fetch), timeout=1)
    assert len(images) == 3


async def test_image_deadline_preserves_completed_images_and_cancels_pending(monkeypatch):
    cancelled = asyncio.Event()
    monkeypatch.setattr(skill_preview_images, "PREVIEW_TIMEOUT", 0.01)

    async def fetch(url, **kwargs):
        if url.endswith("slow.png"):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return image_response(PNG)

    slow = "https://raw.githubusercontent.com/o/r/main/slow.png"
    images = await preview_images(f"![Slow]({slow})\n![Effect]({URL})", fetch)
    assert set(images) == {URL} and cancelled.is_set()
