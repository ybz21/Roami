"""Wake active streams after their conversation events commit; SQLite owns replay."""

import asyncio
from contextlib import contextmanager


class ConversationEvents:
    def __init__(self):
        self.listeners = {}

    @contextmanager
    def subscribe(self, conversation_id):
        changed = asyncio.Event()
        listeners = self.listeners.setdefault(conversation_id, set())
        listeners.add(changed)
        try:
            yield changed
        finally:
            listeners.remove(changed)
            if not listeners:
                del self.listeners[conversation_id]

    def publish(self, conversation_ids):
        for conversation_id in conversation_ids:
            for changed in self.listeners.get(conversation_id, ()):
                changed.set()
