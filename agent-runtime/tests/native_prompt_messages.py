"""Domain fixtures consume dialogue; context tests inspect runtime prompt annotations."""


def dialogue_messages(messages):
    return [
        message
        for message in messages
        if not (
            message["role"] == "system"
            and isinstance(message.get("content"), str)
            and message["content"].startswith(
                (
                    "Current native attempt timing (runtime data,",
                    "Optional workflow instructions read for this request: ",
                    "Optional workflow selection for this request: ",
                )
            )
        )
    ]
