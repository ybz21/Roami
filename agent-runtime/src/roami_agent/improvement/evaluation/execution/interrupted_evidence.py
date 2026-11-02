"""Bounded postmortem extraction inside a disposable copy of the stopped runtime."""

import json

from roami_agent.improvement.domain.contracts import require


def snapshot_metadata(value):
    require(
        isinstance(value, dict)
        and value.get("source") == "interrupted_runtime_snapshot"
        and value.get("complete") is False
        and isinstance(value.get("tool_calls"), list),
        "RSI_EXECUTION_SNAPSHOT_INVALID",
    )
    require(
        all(
            type(value.get(key)) is int and value[key] >= 0
            for key in ("recorded_tool_calls", "captured_tool_calls")
        )
        and value["captured_tool_calls"] == len(value["tool_calls"]) <= value["recorded_tool_calls"]
        and type(value.get("truncated")) is bool,
        "RSI_EXECUTION_SNAPSHOT_INVALID",
    )
    return {
        key: value[key]
        for key in ("source", "complete", "recorded_tool_calls", "captured_tool_calls", "truncated")
    }


def snapshot_program(database="/workspace/runtime.db"):
    return "database = " + json.dumps(str(database)) + "\n" + SNAPSHOT_PROGRAM


SNAPSHOT_PROGRAM = r"""
import json, sqlite3
from pathlib import Path

db = sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True, timeout=1)
db.row_factory = sqlite3.Row
db.execute("PRAGMA trusted_schema=OFF")
steps = 0
def progress():
    global steps
    steps += 1
    return steps > 20000
db.set_progress_handler(progress, 1000)
total = db.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
tools, size, truncated = [], 0, False
for row in db.execute(
    "SELECT t.id,t.tool_name,t.state,substr(t.arguments_json,1,4096) AS arguments_json,"
    "length(t.arguments_json) AS argument_length,substr(m.content_json,1,4096) AS result_json,"
    "length(m.content_json) AS result_length FROM tool_calls t "
    "LEFT JOIN messages m ON m.id=t.result_message_id ORDER BY t.created_ms,t.id LIMIT 2000"
):
    item = dict(row)
    for field, length in (("arguments_json", "argument_length"), ("result_json", "result_length")):
        if (item.pop(length) or 0) > 4096:
            # Include the call identity so truncated arguments cannot imply duplicate work.
            item[field] = json.dumps({"evidence_truncated": item["id"], "prefix": item[field]})
            item[field + "_truncated"] = True
            truncated = True
    if item["state"] in ("planned", "running"):
        item["recorded_state"], item["state"] = item["state"], "unknown"
    encoded = json.dumps(item, ensure_ascii=False).encode()
    if size + len(encoded) > 4000000:
        truncated = True
        break
    tools.append(item)
    size += len(encoded)
tasks = [dict(row) for row in db.execute("SELECT id,state,revision FROM tasks ORDER BY created_ms,id LIMIT 1000")]
db.close()
print(json.dumps({"source":"interrupted_runtime_snapshot", "complete":False,
    "recorded_tool_calls":total, "captured_tool_calls":len(tools),
    "truncated":truncated or total != len(tools), "tool_calls":tools, "tasks":tasks,
    "traces":[]}, ensure_ascii=False))
"""
