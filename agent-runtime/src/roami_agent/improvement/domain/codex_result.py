"""Validate Codex terminal receipts without process or storage access."""

import json

from roami_agent.improvement.domain.contracts import require


def completed_result(raw):
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    threads = [e.get("thread_id") for e in events if e.get("type") == "thread.started"]
    completed = [e for e in events if e.get("type") == "turn.completed"]
    require(
        len(threads) == 1 and isinstance(threads[0], str) and bool(threads[0]),
        "RSI_CODEX_IDENTITY_REQUIRED",
    )
    require(
        len(completed) == 1 and not any(e.get("type") in {"error", "turn.failed"} for e in events),
        "RSI_CODEX_TURN_INCOMPLETE",
    )
    observed_items = [e["item"] for e in events if e.get("type", "").startswith("item.")]
    require(
        all(
            isinstance(i, dict)
            and (
                i.get("type") in {"agent_message", "reasoning"}
                or i.get("type") == "error"
                and set(i) <= {"id", "type", "message"}
                and isinstance(i.get("message"), str)
            )
            for i in observed_items
        ),
        "RSI_UNEXPECTED_MODEL_TOOL",
    )
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    messages = [i.get("text") for i in items if i.get("type") == "agent_message"]
    require(
        len(messages) == 1 and isinstance(messages[0], str) and len(messages[0]) <= 100000,
        "RSI_INVALID_MODEL_OUTPUT",
    )
    usage = completed[0].get("usage", {})
    require(
        all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")),
        "RSI_USAGE_UNKNOWN",
    )
    cached = usage.get("cached_input_tokens", 0)
    require(type(cached) is int and 0 <= cached <= usage["input_tokens"], "RSI_USAGE_UNKNOWN")
    return {
        "text": messages[0],
        "thread_id": threads[0],
        "diagnostics": [i["message"][:1024] for i in items if i.get("type") == "error"][:16],
        "metrics": {
            "tokens": usage["input_tokens"] + usage["output_tokens"],
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cached_input_tokens": cached,
            "model_calls": None,
            "cli_turns": 1,
            "usage_scope": "codex_turn_reported",
            "tool_calls": 0,
        },
    }
