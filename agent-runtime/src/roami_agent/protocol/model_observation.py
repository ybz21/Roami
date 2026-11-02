"""Opaque evaluator identities; ordinary model requests carry no evaluation headers."""

from contextvars import ContextVar

model_observation: ContextVar[dict | None] = ContextVar("model_observation", default=None)
