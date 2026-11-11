"""Throttle reply previews without publishing a final answer."""

from roami_agent.protocol.reply_text_stream import MAX_PREVIEW_CHARS, reply_text_preview


class ReplyStreamPreview:
    def __init__(self, enabled, emit, clock):
        self.enabled, self.emit, self.clock = enabled, emit, clock
        self.index, self.multiple, self.seen = None, False, False
        self.candidate, self.published, self.clipped = None, None, False
        self.flushed = 0

    async def reset(self):
        if self.published is not None:
            await self.emit(None, "generating", False)
        self.index, self.multiple, self.seen = None, False, False
        self.candidate, self.published, self.clipped = None, None, False
        self.flushed = 0

    async def observe_text(self, text):
        if self.enabled and self.index is None:
            await self._publish(text)

    async def observe(self, part):
        if not self.enabled:
            return
        self.seen = True
        if self.index is None:
            self.index = part["index"]
        elif part["index"] != self.index:
            self.multiple = True
        value = (
            reply_text_preview(part["arguments"], limit=MAX_PREVIEW_CHARS + 1)
            if not self.multiple and part["name"] == "reply"
            else None
        )
        await self._publish(value)

    async def _publish(self, value):
        self.seen = True
        self.clipped = value is not None and len(value) > MAX_PREVIEW_CHARS
        self.candidate = value[:MAX_PREVIEW_CHARS] if value else None
        if self.candidate is None:
            if self.published is not None:
                await self.emit(None, "generating", False)
                self.published = None
            return
        if self.candidate == self.published:
            return
        if (
            self.published
            and self.clock() - self.flushed < 0.1
            and len(self.candidate) - len(self.published) < 1024
        ):
            return
        await self.emit(self.candidate, "generating", self.clipped)
        self.published, self.flushed = self.candidate, self.clock()

    async def finish(self, calls, text=""):
        if not self.enabled or not self.seen:
            return
        function = calls[0].get("function", {}) if len(calls) == 1 else {}
        value = (
            reply_text_preview(function.get("arguments"), limit=MAX_PREVIEW_CHARS + 1)
            if function.get("name") == "reply" and not self.multiple
            else text
            if not calls
            else None
        )
        if value:
            await self.emit(value[:MAX_PREVIEW_CHARS], "checking", len(value) > MAX_PREVIEW_CHARS)
        elif self.published is not None:
            await self.emit(None, "generating", False)
