"""Review authenticated native Main calls completed after the model prompt was built."""

from roami_agent.storage.database import rows


def native_main_observations(db, turn, owner):
    recorded = rows(
        db,
        "SELECT t.tool_name,t.arguments_json,substr(t.idempotency_key,length(?)+2) AS call_id,"
        "json_extract(native_content(m.content_json),'$.text') AS result "
        "FROM tool_calls t JOIN messages m ON m.id=t.result_message_id "
        "WHERE t.turn_id=? AND t.state IN ('succeeded','failed') "
        "AND m.turn_id=t.turn_id AND m.conversation_id=? AND m.branch_id=? "
        "AND m.role='tool' AND m.status='completed' AND m.deleted_ms IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id) "
        "AND t.idempotency_key LIKE ? AND EXISTS(SELECT 1 FROM events e "
        "WHERE e.turn_id=t.turn_id AND e.kind='capability.started' "
        "AND e.event_key='capability:'||substr(t.idempotency_key,length(?)+2)||':start') "
        "ORDER BY t.rowid",
        (
            turn["id"],
            turn["id"],
            turn["conversation_id"],
            turn["branch_id"],
            owner,
            turn["id"] + ":native-main-%",
            turn["id"],
        ),
    )
    calls, results = [], []
    for item in recorded:
        if not isinstance(item["result"], str):
            continue
        calls.append(
            {
                "id": item["call_id"],
                "type": "function",
                "function": {"name": item["tool_name"], "arguments": item["arguments_json"]},
            }
        )
        results.append({"role": "tool", "tool_call_id": item["call_id"], "content": item["result"]})
    return (
        [{"role": "assistant", "content": None, "tool_calls": calls}] if calls else []
    ) + results


def review_native_context(context, observations):
    calls_seen = {
        call.get("id")
        for message in context
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict)
    }
    results_seen = {
        message.get("tool_call_id") for message in context if message.get("role") == "tool"
    }
    added = []
    for message in observations:
        if message["role"] == "assistant":
            calls = [call for call in message["tool_calls"] if call["id"] not in calls_seen]
            if calls:
                added.append({**message, "tool_calls": calls})
        elif message["tool_call_id"] not in results_seen:
            added.append(message)
    return [*context, *added]
