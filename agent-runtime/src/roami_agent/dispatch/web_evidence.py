"""Verify retrieval traces, not the semantic truth of market data or model claims."""

import json
from urllib.parse import urlsplit

from roami_agent.protocol.research import research_call_allowed
from roami_agent.storage.database import rows


def retrieved_sources(db, task, run, summary):
    calls = rows(
        db,
        "SELECT x.tool_name,x.arguments_json FROM tool_calls x JOIN turns t ON t.id=x.turn_id WHERE t.branch_id=? AND x.state!='failed'",
        (run["native_branch_id"],),
    )
    if not calls or any(
        not research_call_allowed(call["tool_name"], json.loads(call["arguments_json"]))
        for call in calls
    ):
        return []
    observations = rows(
        db,
        "SELECT body_json,captured_ms FROM resource_observations WHERE task_id=? AND run_id=? ORDER BY captured_ms",
        (task["id"], run["id"]),
    )
    sources = {}
    for observation in observations:
        body = json.loads(observation["body_json"])
        url = body.get("url", "")
        parsed = urlsplit(url)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and body.get("domText", "").strip()
            and url in summary
        ):
            sources[url] = {"url": url, "retrievedMs": observation["captured_ms"]}
    return list(sources.values())
