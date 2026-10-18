from typing import Any, Protocol


class LoopSettings(Protocol):
    timeout_seconds: int
    max_steps: int
    main_instructions: str
    worker_instructions: str

    def timeout_for(self, role: str) -> int: ...


class ContextBuilder(Protocol):
    async def after_turn(self, turn: dict, instructions: str, catalog: list) -> None: ...

    async def build(
        self, turn: dict, instructions: str, catalog: list, completion: dict | None
    ) -> tuple[dict, list]: ...


class TurnWriter(Protocol):
    async def origin(self, turn: dict) -> dict | None: ...
    async def start(self, turn: dict) -> str: ...
    async def delta(self, turn: dict, mid: str, text: str, delta: str) -> None: ...
    async def finish(
        self,
        turn: dict,
        mid: str,
        text: str,
        calls: list,
        usage: dict | None,
        attempt: int,
        *,
        final: bool,
        completion: dict | None,
    ) -> None: ...
    async def fail(self, turn: dict, state: str, code: str, *, completion=None) -> None: ...


class ToolCatalog(Protocol):
    def catalog(self, role: str = "main") -> list[dict]: ...


class ManifestWriter(Protocol):
    async def record(
        self,
        turn: dict,
        attempt: int,
        model_key: str,
        wire_hash: str,
        plan: dict,
        catalog: list,
        role: str,
    ) -> None: ...


class ToolInvoker(Protocol):
    async def invoke(self, turn: dict, mid: str, call: dict, role: str, binding: dict) -> Any: ...
