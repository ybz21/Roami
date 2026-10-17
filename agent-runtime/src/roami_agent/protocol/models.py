from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ModelEvent:
    kind: str
    value: object


class Model(Protocol):
    model: str

    def stream(self, messages: list[dict], tools: list[dict]) -> AsyncIterator[ModelEvent]: ...
