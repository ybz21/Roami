"""Structured project errors cross the CLI boundary without exposing raw diagnostics."""

import json
from types import SimpleNamespace

import pytest

from roami_agent.executors.project import provision_project
from roami_agent.protocol.errors import DomainError


@pytest.mark.parametrize(
    "code,expected",
    [
        ("REMOTE_REQUIRED", "REMOTE_REQUIRED"),
        ("AUTH_REQUIRED", "AUTH_REQUIRED"),
        ("PROJECT_NAME_CONFLICT", "PROJECT_NAME_CONFLICT"),
        ("PROJECT_private account", "PROJECT_PROVISION_UNAVAILABLE"),
        (None, "PROJECT_PROVISION_UNAVAILABLE"),
    ],
)
async def test_project_error_code_preserved(monkeypatch, code, expected):
    async def execute(*args, **kwargs):
        return {"exitCode": 1, "stdout": json.dumps({"error": {"code": code}})}

    monkeypatch.setattr("roami_agent.executors.project.execute", execute)
    task = {"intent_json": json.dumps({"target": {"kind": "new_project", "name": "demo"}})}
    settings = SimpleNamespace(cli_bin="roami", provider_key_environments=lambda: set())
    with pytest.raises(DomainError, match=f"^{expected}$"):
        await provision_project(settings, task, {"launch_id": "run"})
