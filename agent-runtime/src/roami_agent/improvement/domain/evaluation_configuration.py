"""Frozen configuration defaults and identifiers for this bounded context."""

DEFAULTS = {
    "enabled": False,
    "timezone": "Asia/Shanghai",
    "hour": 3,
    "cases_per_day": 60,
    "suite_id": "",
    "machine_ids": [],
    "auto_candidates": False,
    "candidate_policy": {},
}

LEGACY_FIELDS = {"daily_tokens", "daily_episodes"}
