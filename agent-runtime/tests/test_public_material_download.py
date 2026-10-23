"""Pinned large material downloads reject truncated ranges and leave no partial artifact."""

import hashlib
import importlib.util
import io
import sys
from pathlib import Path

import pytest

source = Path(__file__).resolve().parents[2] / "scripts/dev/agent-evaluation/fetch-public.py"
spec = importlib.util.spec_from_file_location("public_material_download", source)
fetcher = importlib.util.module_from_spec(spec)
previous_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(fetcher)
finally:
    sys.dont_write_bytecode = previous_bytecode


class Response(io.BytesIO):
    def __init__(self, data, status, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


def material(data):
    return {
        "path": "large/source.bin",
        "url": "https://huggingface.co/datasets/example/data/resolve/" + "a" * 40 + "/source.bin",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def lock(item):
    return {"schema_version": 1, "sources": [{"benchmark": "fixture", "files": [item]}]}


@pytest.mark.parametrize("range_support", [True, False])
def test_large_download_and_cache_hash_use_bounded_reads(tmp_path, monkeypatch, range_support):
    data = b"original-pinned-data" * 1_700_000
    item = material(data)
    requests = []

    def opening(request, timeout):
        requests.append(request)
        if not range_support:
            return Response(data, 200)
        start, end = map(int, request.get_header("Range").split("=")[1].split("-"))
        return Response(
            data[start : end + 1], 206, {"Content-Range": f"bytes {start}-{end}/{len(data)}"}
        )

    monkeypatch.setattr(fetcher, "urlopen", opening)
    root = tmp_path / "materials"
    result = fetcher.fetch(lock(item), root)
    assert result["files"][0]["state"] == "downloaded_verified"
    assert len(requests) == (5 if range_support else 1)
    assert fetcher.file_sha256(root / item["path"]) == item["sha256"]
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _: pytest.fail("Large source cache must not be loaded in one read"),
    )
    result = fetcher.fetch(lock(item), root)
    assert result["files"][0]["state"] == "verified_existing"
    assert len(requests) == (5 if range_support else 1)


@pytest.mark.parametrize("fault", ["wrong_range", "truncated", "wrong_hash"])
def test_bad_large_download_does_not_publish_partial_file(tmp_path, monkeypatch, fault):
    data = b"x" * 32_000_001
    item = material(data)
    if fault == "wrong_hash":
        item["sha256"] = "0" * 64

    def opening(request, timeout):
        start, end = map(int, request.get_header("Range").split("=")[1].split("-"))
        header = f"bytes {start}-{end}/{len(data)}"
        if fault == "wrong_range" and start:
            header = f"bytes 0-{end}/{len(data)}"
        body = data[start : end + 1]
        if fault == "truncated":
            body = body[:-1]
        return Response(body, 206, {"Content-Range": header})

    monkeypatch.setattr(fetcher, "urlopen", opening)
    root = tmp_path / "materials"
    with pytest.raises(ValueError):
        fetcher.fetch(lock(item), root)
    assert not (root / item["path"]).exists()
    assert not list(root.rglob(".fetch-*"))
