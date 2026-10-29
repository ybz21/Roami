"""Domain model fixtures consume dialogue; dedicated clock tests inspect the full prompt."""


def dialogue_messages(messages):
    return [
        message
        for message in messages
        if not (
            message["role"] == "system"
            and isinstance(message.get("content"), str)
            and message["content"].startswith("Current native attempt timing (runtime data,")
        )
    ]
