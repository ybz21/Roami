"""Verify retrieval traces, not the semantic truth of model or source claims."""

import json
import re
from urllib.parse import urlsplit

from roami_agent.storage.database import row, rows

URL = re.compile(r"https?://[^\s<>\"']+")


def result_urls(value):
    pending = [(value, 0)]
    for _ in range(10000):
        if not pending:
            return
        item, depth = pending.pop()
        if depth > 8:
            continue
        if isinstance(item, dict):
            if item.get("isError") or item.get("exitCode", 0) != 0:
                continue
            if isinstance(item.get("status"), int) and item["status"] >= 400:
                continue
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            try:
                decoded = json.loads(item)
            except (ValueError, RecursionError):
                decoded = None
            if isinstance(decoded, (dict, list, str)) and decoded != item:
                pending.append((decoded, depth + 1))
                continue
            for match in URL.finditer(item):
                url = match[0].rstrip(".,;，。；")
                for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
                    while url.endswith(closing) and url.count(closing) > url.count(opening):
                        url = url[:-1]
                yield url


def retrieved_sources(db, task, run, summary=None):
    observations = rows(
        db,
        "SELECT body_json,captured_ms FROM resource_observations WHERE task_id=? AND run_id=? ORDER BY captured_ms",
        (task["id"], run["id"]),
    )
    sources = {}

    def record(url, captured_ms):
        try:
            parsed = urlsplit(url)
        except ValueError:
            return
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and (summary is None or url in summary)
        ):
            sources[url] = {"url": url, "retrievedMs": captured_ms}

    for observation in observations:
        body = json.loads(observation["body_json"])
        if body.get("domText", "").strip():
            record(body.get("url", ""), observation["captured_ms"])
    started = row(
        db,
        "SELECT turn_id FROM events WHERE conversation_id=? AND task_id=? "
        "AND kind IN ('task.started','task.preparing') AND json_extract(payload_json,'$.runId')=? "
        "ORDER BY id LIMIT 1",
        (task["origin_conversation_id"], task["id"], run["id"]),
    )
    if not started or not started["turn_id"]:
        return list(sources.values())
    prefix = started["turn_id"] + ":"
    calls = rows(
        db,
        "SELECT x.tool_name,x.updated_ms,m.content_json FROM tool_calls x "
        "JOIN messages m ON m.id=x.result_message_id WHERE x.turn_id=? AND x.state='succeeded' "
        "AND x.idempotency_key>=? AND x.idempotency_key<? ORDER BY x.updated_ms",
        (started["turn_id"], prefix, prefix + "\uffff"),
    )
    for call in calls:
        # Discovery schemas and echoed arguments are not retrieval receipts.
        if call["tool_name"] == "mcp_discover" or not call["tool_name"].startswith(
            ("mcp_", "cli_", "http_")
        ):
            continue
        for url in result_urls(json.loads(call["content_json"]).get("text", "")):
            record(url, call["updated_ms"])
    return list(sources.values())
