"""Persist explicit remember requests from their original user message."""

import json
import re

from roami_agent.memory.writer import commit_memory
from roami_agent.storage.database import event

REMEMBER = re.compile(
    r"^(?:(?:请|麻烦)?(?:你)?(?:帮我)?(?:记住|记下|记着|记一下|记下来)"
    r"(?:这(?:一点|件事|个偏好))?|(?:please\s+)?remember\b(?:\s+that\b)?)"
    r"[\s，,:：。.!！]*(?P<body>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def remembered_body(text):
    match = REMEMBER.fullmatch(text.strip())
    if not match:
        return None
    body = match["body"].strip()
    if not body or len(body) > 2000 or body.endswith(("?", "？")):
        return None
    return body


def remember_request(db, owner, conversation_id, message_id, text):
    body = remembered_body(text)
    if body is None:
        return None
    record = commit_memory(
        db,
        owner,
        body[:160],
        body,
        [message_id],
        kind="preference",
        conversation_id=conversation_id,
        confirmed=True,
    )
    event(
        db,
        conversation_id,
        "memory.remembered",
        {
            "memoryId": record["id"],
            "sourceMessageId": message_id,
            "activation": "explicit_request",
        },
        message_id=message_id,
    )
    return record


def direct_user_preference(candidate, sources):
    """Only verbatim user preferences can bypass candidate review."""
    quote = candidate.evidenceQuote
    if candidate.kind != "preference" or not quote or candidate.body.strip() != quote.strip():
        return False
    cited = [source for source in sources if source["id"] in candidate.sourceIds]
    return bool(cited) and all(
        source.get("role") == "user" and quote in json.loads(source["content_json"]).get("text", "")
        for source in cited
    )
