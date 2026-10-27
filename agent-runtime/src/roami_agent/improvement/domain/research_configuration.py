"""Frozen configuration defaults and identifiers for this bounded context."""

DEFAULTS = {
    "enabled": False,
    "repo": "",
    "base_commit": "",
    "allowed_paths": [],
    "model_tokens": 64000,
    "model_seconds": 180,
    "repair_executor": "codex",
    "validation_suite_id": "",
    "max_attempts": 2,
    "observation_days": 2,
}
