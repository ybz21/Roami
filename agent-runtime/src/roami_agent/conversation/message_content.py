"""Read a conversation's human text, public metadata, and model references."""

from collections.abc import Callable
from dataclasses import dataclass


def literal_text(content: dict) -> str:
    return content.get("text", "")


@dataclass(frozen=True)
class MessageContent:
    human_text: Callable[[dict], str] = literal_text
    latest_reference: Callable[[dict], str | None] = lambda _: None
    public_metadata: Callable[[dict], dict] = lambda _: {}
    snapshot_version: Callable[[dict], str | None] = lambda _: None


LITERAL_CONTENT = MessageContent()


def message_content(db) -> MessageContent:
    return getattr(db, "message_content", LITERAL_CONTENT)
