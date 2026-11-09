"""Prove exact artifact bytes from contiguous successful UTF-8 read receipts."""

import hashlib
import json


def text_coverage(receipts, artifact):
    pages = {"bytes": {}, "lines": {}}
    for receipt in receipts:
        try:
            value = json.loads(json.loads(receipt["content_json"])["text"])
            if not isinstance(value, dict):
                continue
            reference = value.get("artifact")
            if (
                not isinstance(reference, dict)
                or reference.get("id") != artifact["id"]
                or reference.get("sha256") != artifact["sha256"]
                or value.get("textAvailable") is not True
                or not isinstance(value.get("text"), str)
                or value.get("truncated")
            ):
                continue
            body = value["text"].encode()
        except (ValueError, KeyError, TypeError, UnicodeError):
            continue
        unit = "lines" if "offsetLines" in value else "bytes"
        offset = value.get("offsetLines" if unit == "lines" else "offset")
        following = value.get("nextOffset")
        if type(offset) is not int or offset < (1 if unit == "lines" else 0):
            continue
        if unit == "bytes":
            if (
                type(following) is not int
                or following != offset + len(body)
                or following > artifact["size_bytes"]
            ):
                continue
            end = following == artifact["size_bytes"] and value.get("hasMore") is False
            if end:
                following = None
        else:
            if following is not None and (type(following) is not int or following <= offset):
                continue
            if following is None and value.get("hasMore", False) is not False:
                continue
        if not body and following is not None:
            continue
        pages[unit].setdefault(offset, []).append(
            (
                body,
                following,
                {"toolCallId": receipt["call_id"], "resultMessageId": receipt["result_id"]},
            )
        )
    for unit, available in pages.items():
        pending = [((1 if unit == "lines" else 0), hashlib.sha256(), 0, [])]
        visited = set()
        while pending:
            offset, digest, length, proof = pending.pop()
            state = (offset, length, digest.hexdigest())
            if state in visited:
                continue
            visited.add(state)
            for body, following, source in available.get(offset, []):
                updated = digest.copy()
                updated.update(body)
                size = length + len(body)
                if size > artifact["size_bytes"]:
                    continue
                reads = [*proof, source]
                if following is None:
                    if size == artifact["size_bytes"] and updated.hexdigest() == artifact["sha256"]:
                        return reads
                else:
                    pending.append((following, updated, size, reads))
    return None
