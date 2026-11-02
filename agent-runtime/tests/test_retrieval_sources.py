"""External receipt URLs preserve exact citations and exclude failed lookups."""

import json

import pytest

from roami_agent.dispatch.web_evidence import result_urls

URL = "https://example.org/wiki/Topic_(details)?q=a%20b&lang=zh#section"


@pytest.mark.parametrize(
    "response",
    [
        {"content": [{"type": "text", "text": "Title: Fixture\nURL: " + URL + "\nExcerpt"}]},
        {"structuredContent": {"results": [{"url": URL}]}},
        {"stdout": json.dumps({"results": [{"url": URL}]})},
        {"body": "[Fixture source](" + URL + ")."},
    ],
)
def test_receipt_urls_keep_balanced_parentheses_query_and_fragment(response):
    assert list(result_urls(json.dumps(response))) == [URL]


@pytest.mark.parametrize(
    "response",
    [
        {"isError": True, "content": [{"type": "text", "text": URL}]},
        {"exitCode": 1, "stdout": URL},
        {"status": 500, "body": URL},
    ],
)
def test_failed_receipts_are_not_treated_as_retrieved_sources(response):
    assert list(result_urls(response)) == []
