"""Bounded JSON document loading."""

import json

from roami_agent.improvement.domain.contracts import require


def load_json(path, *, maximum=16_000_000):
    require(path.stat().st_size <= maximum, "RSI_INPUT_TOO_LARGE")
    return json.loads(path.read_text(), parse_constant=lambda value: require(False))
