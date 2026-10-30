"""Request context crosses the private bridge; model connections stay on the host."""

import math
from dataclasses import replace

from roami_agent.improvement.domain.contracts import require

ERROR = "RSI_CONTAINER_MODEL_CONTEXT_INVALID"


def role_instructions(settings):
    return {"main": settings.main_instructions, "worker": settings.worker_instructions}


def instruction_settings(settings, raw):
    require(
        isinstance(raw, dict)
        and set(raw) == {"main", "worker"}
        and all(isinstance(value, str) for value in raw.values()),
        "RSI_CONTAINER_ROLE_INSTRUCTIONS_INVALID",
    )
    return replace(settings, main_instructions=raw["main"], worker_instructions=raw["worker"])


def model_context(settings):
    return {
        "main_window": settings.route("main").context_window,
        "worker_window": settings.route("worker").context_window,
        "reserve_tokens": settings.reserve_tokens,
        "keep_recent_tokens": settings.keep_recent_tokens,
        "compaction_ratio": settings.compaction_ratio,
    }


def context_settings(settings, raw):
    require(isinstance(raw, dict) and set(raw) == set(model_context(settings)), ERROR)
    for key in ("main_window", "worker_window"):
        value = raw[key]
        require(value is None or type(value) is int and 1 <= value <= 100_000_000, ERROR)
    for key in ("reserve_tokens", "keep_recent_tokens"):
        require(type(raw[key]) is int and 1 <= raw[key] <= 1_000_000, ERROR)
    ratio = raw["compaction_ratio"]
    require(type(ratio) in (int, float) and math.isfinite(ratio) and 0 < ratio < 1, ERROR)
    return replace(
        settings,
        context_window=raw["main_window"],
        worker_route=replace(settings.route("worker"), context_window=raw["worker_window"]),
        reserve_tokens=raw["reserve_tokens"],
        keep_recent_tokens=raw["keep_recent_tokens"],
        compaction_ratio=ratio,
    )
