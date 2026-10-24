"""Request-local policy binding; concurrent conversations never share overrides."""

from contextvars import ContextVar

policy_binding = ContextVar("roami_improvement_policy", default=None)


def policy_value(name, fallback):
    binding = policy_binding.get()
    return binding["policy"].get(name, fallback) if binding else fallback
