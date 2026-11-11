"""Delivery tools return payloads to the loop, but persist only their receipts."""


def delivery_receipt(name, value):
    if not isinstance(value, dict) or value.get("error"):
        return value
    if name in {"reply", "task_reply", "task_queue_reply"} and isinstance(value.get("reply"), str):
        return {**{key: item for key, item in value.items() if key != "reply"}, "accepted": True}
    if name == "ask_user" and value.get("state") == "waiting_user" and value.get("question"):
        return {key: item for key, item in value.items() if key != "question"}
    return value


def delivery_output(name, state, value):
    if isinstance(value, dict) and value.get("error"):
        return value
    if state == "succeeded" and name in {"reply", "ask_user"}:
        return None
    return delivery_receipt(name, value) if state == "succeeded" else value
