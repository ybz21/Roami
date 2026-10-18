"""Explicit role-specific provider configuration without credential material."""

from dataclasses import dataclass, field

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import model_endpoint


@dataclass(frozen=True)
class ModelRoute:
    endpoint: str
    name: str
    key_env: str
    timeout_seconds: int
    max_retries: int = 2
    capabilities: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)

    @classmethod
    def worker(cls, raw, fallback):
        if not isinstance(raw, dict):
            raise DomainError("INVALID_MODEL_CONFIG")
        route = cls(
            endpoint=model_endpoint(raw.get("endpoint", fallback.endpoint)),
            name=raw.get("name", fallback.name),
            key_env=raw.get("key_env", fallback.key_env),
            timeout_seconds=raw.get("timeout_seconds", fallback.timeout_seconds),
            max_retries=raw.get("max_retries", fallback.max_retries),
            capabilities=raw.get("capabilities", {}),
            cache=raw.get("cache", {}),
            parameters=raw.get("parameters", {}),
        )
        if (
            not isinstance(route.name, str)
            or not route.name
            or not route.endpoint
            or not isinstance(route.key_env, str)
            or not route.key_env
            or not route.key_env.isidentifier()
            or isinstance(route.timeout_seconds, bool)
            or not isinstance(route.timeout_seconds, int)
            or not 1 <= route.timeout_seconds <= 1_000_000
            or isinstance(route.max_retries, bool)
            or not isinstance(route.max_retries, int)
            or not 0 <= route.max_retries <= 3
            or not isinstance(route.capabilities, dict)
            or not isinstance(route.cache, dict)
            or not isinstance(route.parameters, dict)
        ):
            raise DomainError("INVALID_MODEL_CONFIG")
        return route
