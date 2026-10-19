"""Reasoning levels advertised for known families; compatible gateways may add models."""

import re

from roami_agent.protocol.errors import DomainError

EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def reasoning_efforts(name):
    model = name.lower().rsplit("/", 1)[-1]
    if re.match(r"glm-5\.3(?:-|$)", model):
        return ["low", "high", "max"]
    if re.match(r"glm-5\.2(?:-|$)", model):
        return ["high", "max"]
    if re.match(r"gpt-(?:6-(?:astra|sol|luna)|6\.1-sol)(?:-|$)", model):
        levels = ["low", "medium", "high", "xhigh", "max"]
        return ["none", *levels] if re.match(r"gpt-6-(?:sol|luna)(?:-|$)", model) else levels
    return list(EFFORTS)


def with_reasoning_effort(parameters, name, value):
    if not isinstance(name, str):
        raise DomainError("INVALID_MODEL_CONFIG")
    result = dict(parameters)
    if value is not None and (not isinstance(value, str) or value not in reasoning_efforts(name)):
        raise DomainError("MODEL_REASONING_UNSUPPORTED")
    result.pop("reasoning_effort", None)
    if value is not None:
        result["reasoning_effort"] = value
    return result
