"""Authenticated references to immutable native journal payloads."""

import hashlib
import hmac
import json
import sys
from collections import OrderedDict

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.native_session_files import NativeSessionFiles


class NativePayloads:
    def __init__(self, root, key):
        self.files, self.key = NativeSessionFiles(root), key
        self.cache = OrderedDict()
        self.bytes = 0

    def reference(self, ident, segment, record, field):
        value = record["payload"][field]
        body = {
            "sessionId": ident,
            "filename": segment["filename"],
            "sha256": segment["sha256"],
            "raw_sha256": segment["rawSha256"],
            "raw_bytes": segment["rawBytes"],
            "seq": record["seq"],
            "entityId": record["entityId"],
            "field": field,
            "contentSha256": hashlib.sha256(encoded(value).encode()).hexdigest(),
        }
        body["signature"] = hmac.new(self.key, encoded(body).encode(), hashlib.sha256).hexdigest()
        return encoded({"_nativePayload": body})

    def resolve(self, content):
        if not isinstance(content, str) or not content.startswith('{"_nativePayload":'):
            return content
        try:
            reference = json.loads(content)["_nativePayload"]
            unsigned = {key: value for key, value in reference.items() if key != "signature"}
            expected = hmac.new(self.key, encoded(unsigned).encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(reference["signature"], expected) or reference[
                "field"
            ] not in {"content", "arguments"}:
                raise ValueError("reference signature")
            cache_key = (reference["sessionId"], reference["filename"], reference["sha256"])
            cached = self.cache.get(cache_key)
            if cached is None:
                raw = self.files.archive_bytes(reference["sessionId"], reference)
                index = {}
                size = 0
                for line in raw.splitlines():
                    record = json.loads(line)
                    if record["nativeSessionId"] != reference["sessionId"]:
                        raise ValueError("segment identity")
                    fields = {
                        field: encoded(record["payload"][field])
                        for field in ("content", "arguments")
                        if field in record["payload"]
                    }
                    if not fields:
                        continue
                    index[record["seq"]] = (record["entityId"], fields)
                    size += (
                        sys.getsizeof(record["seq"])
                        + sys.getsizeof(record["entityId"])
                        + sys.getsizeof(fields)
                        + sys.getsizeof(index[record["seq"]])
                        + sum(sys.getsizeof(value) for value in fields.values())
                    )
                size += sys.getsizeof(index)
                if size <= 64 * 1024 * 1024:
                    while self.cache and self.bytes + size > 64 * 1024 * 1024:
                        _, (_, previous_size) = self.cache.popitem(last=False)
                        self.bytes -= previous_size
                    self.cache[cache_key] = (index, size)
                    self.bytes += size
            else:
                self.cache.move_to_end(cache_key)
                index, _ = cached
            entity, fields = index[reference["seq"]]
            if entity != reference["entityId"]:
                raise ValueError("reference identity")
            value = fields[reference["field"]]
            if hashlib.sha256(value.encode()).hexdigest() != reference["contentSha256"]:
                raise ValueError("reference digest")
            return value
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise DomainError("NATIVE_PAYLOAD_UNAVAILABLE", 503) from exc
        raise DomainError("NATIVE_PAYLOAD_UNAVAILABLE", 503)
