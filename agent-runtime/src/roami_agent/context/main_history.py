"""Main keeps user constraints and reads older execution records on demand."""

from roami_agent.context.token_estimate import messages_tokens, request_basis, request_tokens
from roami_agent.protocol.serialization import encoded


def main_history(plan, configuration):
    messages, start = plan["messages"], plan["currentTurnStart"]
    source_ids = plan["modelSourceMessageIds"]
    receipts = plan.get("modelHandoffReceipts", {})
    replies = set(plan.get("modelRepliedMessageIds", []))
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
    if previous_reply is not None:
        replies.discard(source_ids[previous_reply])
    selected = [
        index
        for index, message in enumerate(messages)
        if index >= start
        or (message["role"] in {"user", "system"} and not plan["modelAgentTaskInstructions"][index])
        or index == previous_reply
        or source_ids[index] in receipts
        or source_ids[index] in replies
    ]
    if len(selected) == len(messages) and not receipts and not replies:
        return plan
    selected_set = set(selected)
    suppressed = [
        source_ids[i] for i in range(len(messages)) if i not in selected_set and source_ids[i]
    ]
    visible = [
        {
            "role": "assistant",
            "content": "Historical task handoff (accepted, not completion or new authorization): "
            + encoded(receipts[source_ids[i]]),
        }
        if i < start and source_ids[i] in receipts
        else {
            "role": "assistant",
            "content": "Historical assistant reply (delivered, content omitted): "
            "This request received a reply. Omission is not evidence of an unanswered question "
            "and delivery is not proof of task completion. Use conversation_history for the exact "
            "reply; do not repeat old answers unless the user asks.",
        }
        if i < start and source_ids[i] in replies
        else messages[i]
        for i in selected
    ]
    return dict(
        plan,
        messages=visible,
        currentTurnStart=sum(i < start for i in selected),
        historyView="main_briefing",
        historyViewVersion=3,
        requestBasis=request_basis(
            dict(configuration, historyView="main_briefing", historyViewVersion=3)
        ),
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
