"""Main keeps user constraints and reads older execution records on demand."""

from roami_agent.context.token_estimate import messages_tokens, request_basis, request_tokens


def main_history(plan, configuration):
    messages, start = plan["messages"], plan["currentTurnStart"]
    previous_reply = next(
        (
            index
            for index in range(start - 1, -1, -1)
            if messages[index]["role"] == "assistant" and not messages[index].get("tool_calls")
        ),
        None,
    )
    if previous_reply is not None and plan["modelDetailedAnswers"][previous_reply]:
        previous_reply = None
    selected = [
        index
        for index, message in enumerate(messages)
        if index >= start
        or (message["role"] in {"user", "system"} and not plan["modelAgentTaskInstructions"][index])
        or index == previous_reply
    ]
    if len(selected) == len(messages):
        return plan
    selected_set = set(selected)
    source_ids = plan["modelSourceMessageIds"]
    suppressed = [
        source_ids[i] for i in range(len(messages)) if i not in selected_set and source_ids[i]
    ]
    visible = [messages[i] for i in selected]
    return dict(
        plan,
        messages=visible,
        currentTurnStart=sum(i < start for i in selected),
        historyView="main_briefing",
        requestBasis=request_basis(dict(configuration, historyView="main_briefing")),
        usageTokens=None,
        trailingTokens=None,
        historyTokens=messages_tokens(visible),
        sourceMessageIds=[mid for mid in plan["sourceMessageIds"] if mid not in suppressed],
        suppressedSourceMessageIds=suppressed,
        estimatedTokens=request_tokens(
            [{"role": "system", "content": configuration["instructions"]}] + visible,
            configuration["catalog"],
        ),
    )
