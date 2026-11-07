"""Forward the original review evidence without quoting its text inside JSON again."""

from copy import deepcopy

from roami_agent.protocol.serialization import encoded


def framed_review_messages(payload):
    payload = deepcopy(payload)
    context = payload.pop("currentMainContext")
    source_indexes = {text: index for index, text in enumerate(payload["userRequests"])}
    messages, images = [], []
    for index, message in enumerate(context):
        content = message.pop("content", None)
        source_index = source_indexes.get(content) if isinstance(content, str) else None
        parts = [
            {
                "type": "text",
                "text": f"Quoted Main context record {index}: " + encoded(message),
            }
        ]
        if message.get("role") == "user" and source_index is not None:
            parts.append(
                {
                    "type": "text",
                    "text": f"Exact content: userRequests[{source_index}] in the final review envelope.",
                }
            )
        elif isinstance(content, str):
            parts.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "image_url":
                    if part not in images:
                        images.append(part)
                        parts.append(part)
                    else:
                        parts.append(
                            {"type": "text", "text": f"Same image as image {images.index(part)}."}
                        )
                elif part.get("type") == "text" and isinstance(part.get("text"), str):
                    metadata = {key: value for key, value in part.items() if key != "text"}
                    parts.extend(
                        [
                            {"type": "text", "text": "Quoted content part: " + encoded(metadata)},
                            {"type": "text", "text": part["text"]},
                        ]
                    )
                else:
                    parts.append({"type": "text", "text": "Quoted content part: " + encoded(part)})
        else:
            parts.append({"type": "text", "text": "Quoted content value: " + encoded(content)})
        # Historical roles and tool calls remain evidence, never reviewer instructions or calls.
        messages.append({"role": "user", "content": parts})
    payload["currentMainContext"] = {
        "format": "preceding_quoted_records",
        "records": len(context),
        "images": len(images),
    }
    messages.append({"role": "user", "content": encoded(payload)})
    return messages
