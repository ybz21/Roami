import asyncio


class DomainError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


class ToolCancellation(asyncio.CancelledError):
    def __init__(self, *, input_stopped):
        super().__init__()
        self.input_stopped = input_stopped is True
