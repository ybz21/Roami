"""Align whitespace-only quote differences while retaining the actual source span."""

import re

MAX_QUOTE_LENGTH = 8000


def quote_text(value):
    return re.sub(r"\s+", " ", value).strip()


def source_quote(text, quote, prior_quotes=()):
    if not isinstance(quote, str) or not quote.strip():
        return None
    if quote in prior_quotes and quote in text:
        return quote
    needle = quote_text(quote)
    prior = [p for p in prior_quotes if quote_text(p) == needle and p in text]
    if len(prior) == 1:
        return prior[0]
    if quote in text:
        return quote
    normalized = re.sub(r"\s+", " ", text)
    start = normalized.find(needle)
    if start < 0:
        return None
    # Keep offsets relative to the untrimmed source, including its leading whitespace.
    end, cursor, original_start = start + len(needle), 0, None
    for match in re.finditer(r"\s+|\S+", text):
        space = match.group().isspace()
        size = 1 if space else len(match.group())
        if original_start is None and cursor <= start < cursor + size:
            original_start = match.start() if space else match.start() + start - cursor
        if cursor < end <= cursor + size:
            original_end = match.end() if space else match.start() + end - cursor
            return text[original_start:original_end]
        cursor += size
    return None
