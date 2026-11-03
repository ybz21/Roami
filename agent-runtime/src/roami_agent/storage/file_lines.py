"""Bounded, one-indexed text pages over a verified open file."""

import base64
import hashlib
import os
import stat

from roami_agent.protocol.errors import DomainError


def read_line_page(file, offset=1, limit=2000):
    before = os.fstat(file.fileno())
    if not stat.S_ISREG(before.st_mode):
        raise DomainError("FILE_TYPE_OR_SIZE_UNSUPPORTED")
    selected, digestor, size, count, next_line = bytearray(), hashlib.sha256(), 0, 0, None
    truncated = False
    for count, line in enumerate(file, 1):
        digestor.update(line)
        size += len(line)
        if count < offset:
            continue
        if count >= offset + limit or len(selected) + len(line) > 50000:
            if not selected and count == offset:
                selected.extend(line[:50000])
                truncated = len(line) > 50000
                next_line = count + 1
            next_line = next_line or count
            continue
        if next_line is None:
            selected.extend(line)
    after = os.fstat(file.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or size != before.st_size:
        raise DomainError("FILE_CHANGED", 409)
    try:
        text, encoding = selected.decode("utf-8"), "utf-8"
    except UnicodeDecodeError as exc:
        if truncated and exc.reason == "unexpected end of data" and exc.end == len(selected):
            text, encoding = selected[: exc.start].decode("utf-8"), "utf-8"
        else:
            text, encoding = base64.b64encode(selected).decode(), "base64"
    return {
        "data": text,
        "encoding": encoding,
        "offsetLines": offset,
        "sizeBytes": size,
        "sha256": digestor.hexdigest(),
        "totalLines": count,
        "truncated": truncated,
        "nextOffset": next_line if next_line is not None and next_line <= count else None,
    }
