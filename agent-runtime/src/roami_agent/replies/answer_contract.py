"""Reject ordinary delivery mistakes without rewriting requested content."""

import re

from roami_agent.protocol.errors import DomainError
from roami_agent.replies.task_progress import request_language


def validate_answer(args, source):
    mode, text = args["mode"], args["text"]
    quote = args.get("scopeQuote")
    if mode != "brief":
        if not quote or quote not in source:
            raise DomainError("REPLY_SCOPE_QUOTE_REQUIRED", 409)
        return text
    language = request_language(source, args["language"], args.get("languageQuote"))
    has_han = any("\u3400" <= char <= "\u9fff" for char in text)
    prose = re.sub(r"\[[^\]]*\]\([^)]*\)|(?:https?://|/api/)\S+|`[^`]*`", "", text)
    first_letter = next((char for char in prose if char.isalpha()), "")
    if language == "en" and "\u3400" <= first_letter <= "\u9fff":
        raise DomainError("REPLY_LANGUAGE_MISMATCH", 409)
    if re.search(
        r"随时告诉|再告诉我|需要.{0,30}我.{0,30}[吗?？]|let me know|feel free|if you (?:need|want)",
        text,
        re.IGNORECASE,
    ):
        raise DomainError("REPLY_BOILERPLATE", 409)
    if re.search(r"(?:stopConfirmed|outcomeKnown|inputStopped)\s*[=:]", text) or (
        has_han and re.search(r"\b(?:interrupted|succeeded|task_steer)\b", text)
    ):
        raise DomainError("REPLY_INTERNAL_FIELDS", 409)
    return text
