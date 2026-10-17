from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from roami_agent.protocol.errors import DomainError


def model_endpoint(value):
    if value == "":
        return ""
    try:
        parsed = urlsplit(value)
        if (
            not isinstance(value, str)
            or any(ord(char) <= 32 for char in value)
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.scheme not in {"https", "http"}
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise DomainError("INVALID_MODEL_ENDPOINT") from exc
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise DomainError("MODEL_ENDPOINT_REQUIRES_TLS")
    return value.rstrip("/")


@dataclass(frozen=True)
class ModelEvent:
    kind: str
    value: object


class Model(Protocol):
    model: str

    def stream(self, messages: list[dict], tools: list[dict]) -> AsyncIterator[ModelEvent]: ...
