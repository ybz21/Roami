"""Verify retrieval traces, not the semantic truth of market data or model claims."""

import json
import re
from urllib.parse import urlsplit

from roami_agent.protocol.research import research_call_allowed
from roami_agent.storage.database import rows


def result_urls(value):
    pending, urls = [value], set()
    while pending and len(urls) < 64:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            for match in re.finditer(r"https?://[^\s<>\"`\[\]{}]+", item):
                url = match[0].rstrip(".,;:!?，。；：！？")
                while url.endswith(")") and url.count(")") > url.count("("):
                    url = url[:-1]
                try:
                    if urlsplit(url).hostname:
                        urls.add(url)
                except ValueError:
                    continue
                if len(urls) >= 64:
                    break
    return urls


def retrieved_sources(db, task, run, summary):
    calls = rows(
        db,
        "SELECT x.tool_name,x.arguments_json,x.effect FROM tool_calls x JOIN turns t ON t.id=x.turn_id WHERE t.branch_id=? AND x.state!='failed'",
        (run["native_branch_id"],),
    )
    if not calls or any(
        not research_call_allowed(
            call["tool_name"], json.loads(call["arguments_json"]), effect=call["effect"]
        )
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
    calls = rows(
        db,
        "SELECT x.tool_name,x.updated_ms,m.content_json FROM tool_calls x "
        "JOIN turns t ON t.id=x.turn_id JOIN messages m ON m.id=x.result_message_id "
        "WHERE t.branch_id=? AND x.state='succeeded' AND x.effect='read' "
        "AND x.tool_name GLOB 'mcp_*' AND x.tool_name!='mcp_discover' "
        "AND EXISTS(SELECT 1 FROM events e WHERE e.turn_id=x.turn_id AND e.task_id=? "
        "AND e.kind IN ('task.started','task.preparing') AND json_extract(e.payload_json,'$.runId')=?)",
        (run["native_branch_id"], task["id"], run["id"]),
    )
    reported = result_urls(summary)
    for call in calls:
        try:
            result = json.loads(json.loads(call["content_json"])["text"])
        except (ValueError, TypeError, KeyError):
            continue
        if not isinstance(result, dict) or result.get("error") or result.get("isError"):
            continue
        retrieved = result_urls([result.get("content"), result.get("structuredContent")])
        for url in sorted(retrieved & reported):
            sources[url] = {
                "url": url,
                "retrievedMs": call["updated_ms"],
                "kind": "mcp",
                "toolName": call["tool_name"],
            }
    return list(sources.values())
