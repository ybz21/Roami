"""Reuse billed text-prefix input counts without discounting later request usage."""

import hashlib
import json


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def input_bytes(messages, tools):
    return len(json.dumps([messages, tools], ensure_ascii=False).encode())


class InputReservation:
    def __init__(self):
        self.previous = None

    def estimate(self, messages, tools):
        size = input_bytes(messages, tools)
        text_only = all(
            isinstance(m, dict) and (m.get("content") is None or isinstance(m.get("content"), str))
            for m in messages
        )
        snapshot = (
            {
                "messages": tuple(_fingerprint(m) for m in messages),
                "tools": _fingerprint(tools),
                "bytes": size,
            }
            if text_only
            else None
        )
        prior = self.previous
        if (
            snapshot is not None
            and prior is not None
            and snapshot["tools"] == prior["tools"]
            and len(snapshot["messages"]) > len(prior["messages"])
            and snapshot["messages"][: len(prior["messages"])] == prior["messages"]
        ):
            added = max(0, size - prior["bytes"])
            basis = {
                "kind": "metered_text_prefix",
                "prefix_input_tokens": prior["input_tokens"],
                "prefix_messages": len(prior["messages"]),
                "added_bytes": added,
            }
            return prior["input_tokens"] + added + 4096, snapshot, basis
        return size + 4096, snapshot, {"kind": "serialized_bytes"}

    def observe(self, snapshot, usage):
        if (
            snapshot is not None
            and isinstance(usage, dict)
            and type(usage.get("inputTokens")) is int
            and usage["inputTokens"] >= 0
            and type(usage.get("outputTokens")) is int
            and usage["outputTokens"] >= 0
            and type(usage.get("requestAttempts")) is int
            and usage.get("requestAttempts") == 1
            and usage.get("retryUsageKnown") is True
        ):
            self.previous = {**snapshot, "input_tokens": usage["inputTokens"]}
        else:
            self.previous = None
