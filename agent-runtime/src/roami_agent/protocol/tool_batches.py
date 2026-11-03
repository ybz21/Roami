"""Resolve CLI facades before checking turn-ending tool exclusivity."""

from roami_agent.protocol.errors import DomainError

ENDING_TOOLS = frozenset({"ask_user", "task_reply", "task_queue_reply", "reply"})


def invalid_ending_batch(tools, calls, role):
    if len(calls) < 2:
        return False
    for call in calls:
        try:
            name = tools.validate(call, role)[0].name
        except (DomainError, KeyError, TypeError):
            name = call["function"]["name"]
        if name in ENDING_TOOLS:
            return True
    return False
