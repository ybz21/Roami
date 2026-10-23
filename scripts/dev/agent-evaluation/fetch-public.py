"""Fetch pinned source materials privately; this does not register runnable cases."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import urlopen


def fetch(lock, root, *, only=(), maximum=256_000_000):
    if lock.get("schema_version") != 1 or not set(only).issubset(
        s["benchmark"] for s in lock["sources"]
    ):
        raise ValueError("Unknown lock version or benchmark selection")
    if root.is_symlink():
        raise ValueError("Private output must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_mode & 0o077:
        raise ValueError("Output directory must have mode 0700")
    items = {
        item["path"]: item
        for source in lock["sources"]
        if not only or source["benchmark"] in only
        for item in source.get("files", [])
    }
    if sum(item["bytes"] for item in items.values()) > maximum:
        raise ValueError("Pinned download exceeds maximum total bytes")
    result = []
    for name, item in sorted(items.items()):
        relative = PurePosixPath(name)
        url = urlparse(item["url"])
        if relative.is_absolute() or ".." in relative.parts or not name:
            raise ValueError("Invalid material path")
        if url.scheme != "https" or url.hostname not in {
            "raw.githubusercontent.com",
            "huggingface.co",
        }:
            raise ValueError("Only pinned official source URLs are supported")
        path = root / relative
        parent = root
        for segment in relative.parts[:-1]:
            parent = parent / segment
            if parent.is_symlink():
                raise ValueError("Material parent must not be a symlink")
            parent.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink():
            raise ValueError("Material must not be a symlink")
        if path.exists():
            if (
                path.stat().st_size != item["bytes"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
            ):
                raise ValueError("Existing material hash differs: " + name)
            result.append({"path": name, "state": "verified_existing"})
            continue
        descriptor, temporary = tempfile.mkstemp(prefix=".fetch-", dir=path.parent)
        try:
            size, checksum = 0, hashlib.sha256()
            with (
                os.fdopen(descriptor, "wb") as output,
                urlopen(item["url"], timeout=60) as response,
            ):
                while chunk := response.read(65536):
                    size += len(chunk)
                    if size > item["bytes"]:
                        raise ValueError("Material size exceeds pinned length")
                    checksum.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size != item["bytes"] or checksum.hexdigest() != item["sha256"]:
                raise ValueError("Downloaded material does not match pin: " + name)
            os.link(temporary, path)
            result.append({"path": name, "state": "downloaded_verified"})
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"files": result, "scope": "source_materials_only_not_runnable_suite"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--max-total-bytes", type=int, default=256_000_000)
    args = parser.parse_args()
    result = fetch(
        json.loads(args.lock.read_text()),
        args.output_root,
        only=args.only,
        maximum=args.max_total_bytes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
