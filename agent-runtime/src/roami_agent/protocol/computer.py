"""Explicit desktop selection; the runtime never creates a replacement user desktop."""

import re

from roami_agent.protocol.errors import DomainError


def computer_config(value):
    if not isinstance(value, dict) or set(value) - {"enabled", "display", "image_side"}:
        raise DomainError("INVALID_COMPUTER_CONFIG")
    result = {"enabled": False, "image_side": 1280, **value}
    if (
        not isinstance(result["enabled"], bool)
        or type(result["image_side"]) is not int
        or not 256 <= result["image_side"] <= 1600
        or (
            "display" in result
            and (
                not isinstance(result["display"], str)
                or not re.fullmatch(r":[0-9]{1,5}(?:\.[0-9]{1,2})?", result["display"])
            )
        )
    ):
        raise DomainError("INVALID_COMPUTER_CONFIG")
    return result
