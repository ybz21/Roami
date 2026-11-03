"""Declared native model requirements use the saved Worker route."""

from roami_agent.protocol.errors import DomainError


def native_model_capabilities(settings, requirements):
    names = [value.removeprefix("model:") for value in requirements if value.startswith("model:")]
    if not names:
        return None
    saved = settings.route("worker").capabilities
    observed = {name: saved.get(name) is True for name in names}
    if not all(observed.values()):
        raise DomainError("ROUTING_CAPABILITY_UNAVAILABLE")
    return {"kind": "native_model_capabilities", "role": "worker", "capabilities": observed}
