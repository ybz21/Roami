"""Lease failure classification uses actual stop evidence without replaying tools."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from roami_agent.executors.workspace import hold_workspace
from roami_agent.protocol.errors import DomainError


@pytest.mark.parametrize("kind", ["os", "value", "known", "unknown", "cancel"])
@pytest.mark.parametrize("stop_evidence", [True, False, None])
async def test_workspace_failure_release_and_unknown_protection(tmp_path, kind, stop_evidence):
    released = tmp_path / "release.json"
    cli = tmp_path / "roami"
    cli.write_text(
        f"#!{sys.executable}\n"
        "import json,sys,pathlib\n"
        "sys.stdin.readline()\n"
        f"print(json.dumps({{'state':'native_running','workspace':{{'workspaceId':'w','directory':{str(tmp_path)!r}}}}}),flush=True)\n"
        "frame=sys.stdin.readline()\n"
        f"pathlib.Path({str(released)!r}).write_text(frame)\n"
        "print(json.dumps({'released':True}),flush=True)\n"
    )
    cli.chmod(0o700)
    settings = SimpleNamespace(cli_bin=str(cli), provider_key_environments=lambda: set())
    task = {
        "intent_json": json.dumps({"target": {"kind": "project", "projectId": "p"}}),
        "budget_json": "{}",
    }
    error = {
        "os": OSError("private diagnostic"),
        "value": ValueError("private diagnostic"),
        "known": DomainError("MODEL_HTTP_401"),
        "unknown": DomainError("TOOL_OUTCOME_UNKNOWN"),
        "cancel": asyncio.CancelledError(),
    }[kind]
    observed = []

    async def stopped():
        observed.append(True)
        return stop_evidence

    confirmed = kind != "unknown" and (
        stop_evidence is True or (stop_evidence is None and kind in {"known", "cancel"})
    )
    with pytest.raises(type(error) if confirmed else DomainError) as caught:
        async with hold_workspace(
            settings,
            task,
            {"launch_id": "run"},
            stopped=stopped if stop_evidence is not None else None,
        ):
            raise error
    if confirmed:
        assert caught.value is error
        assert json.loads(released.read_text()) == {
            "state": "cancelled" if kind == "cancel" else "failed",
            "stopped": True,
        }
    else:
        assert caught.value.code == "NATIVE_WORKSPACE_OUTCOME_UNKNOWN"
        assert caught.value.__context__ is error
        assert not released.exists()
    assert observed == ([True] if stop_evidence is not None else [])
