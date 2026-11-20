"""Bounded reads of the exact host-prepared context for native continuation."""

from roami_agent.context.swarm_coordination import CURRENT_BATCH_PREFIX
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded

INLINE_LIMIT = 24 * 1024
PAGE_BYTES = 8 * 1024
READ_CAPABILITY = "native_context_read"


class NativePrompt:
    def __init__(self, messages):
        self.messages = tuple(encoded(message).encode() for message in messages)
        self.system_indices = [
            index for index, message in enumerate(messages) if message["role"] == "system"
        ]
        self.batch_index = next(
            (
                index
                for index in self.system_indices
                if isinstance(messages[index].get("content"), str)
                and messages[index]["content"].startswith(CURRENT_BATCH_PREFIX)
            ),
            None,
        )

    def read(self, arguments):
        if not arguments:
            return {
                "messageCount": len(self.messages),
                "systemIndices": self.system_indices,
                "coordinationIndex": self.batch_index,
            }
        index, offset = arguments.get("index"), arguments.get("offset", 0)
        if (
            set(arguments) - {"index", "offset"}
            or type(index) is not int
            or not 0 <= index < len(self.messages)
            or type(offset) is not int
        ):
            raise DomainError("INVALID_TOOL_ARGUMENTS")
        data = self.messages[index]
        if not 0 <= offset < len(data) or data[offset] & 0b11000000 == 0b10000000:
            raise DomainError("INVALID_TOOL_ARGUMENTS")
        # The input is valid UTF-8, so only a partial trailing character can be dropped.
        text = data[offset : offset + PAGE_BYTES].decode(errors="ignore")
        end = offset + len(text.encode())
        return {
            "index": index,
            "offset": offset,
            "text": text,
            "nextOffset": end if end < len(data) else None,
        }
