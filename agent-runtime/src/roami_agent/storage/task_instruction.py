"""Select the instruction actually submitted to a persistent task provider."""


def current_instruction(intent):
    continuation = intent.get("continuation", {}).get("text")
    if intent.get("target", {}).get("kind") == "session" and continuation:
        return continuation
    return intent["goal"]
