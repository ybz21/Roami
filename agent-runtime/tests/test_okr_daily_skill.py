import runpy
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/okr-development/assets/.roami/okr/skills/daily-operations/scripts/wake_main.py"
)
waker = SimpleNamespace(**runpy.run_path(str(SCRIPT)))
CommandFailure, run_cli, wake = waker.CommandFailure, waker.run_cli, waker.wake


@pytest.fixture(autouse=True)
def external_trigger(monkeypatch):
    monkeypatch.delenv("ROAMI_AGENT_CALLER_ROLE", raising=False)
    monkeypatch.delenv("ROAMI_AGENT_TURN_ID", raising=False)


class Host:
    def __init__(self, *, supported=True, identity=None, final=None):
        self.calls = []
        self.supported, self.identity, self.final = supported, identity or {}, final

    def __call__(self, args):
        self.calls.append(args)
        if args == ["agent", "status"]:
            return {"projectGoalDailyWake": self.supported, "projectMainWake": True}
        if args[:2] == ["agent", "identity"]:
            return {
                "kind": "project_main",
                "projectId": "project-a",
                "conversationId": "original-main",
                "activeBranchId": "branch",
                **self.identity,
            }
        assert args[:3] == ["swarm", "daily", "original-swarm"]
        if isinstance(self.final, Exception):
            raise self.final
        return self.final or {
            "state": "prepared" if "--dry-run" in args else "accepted",
            "delivered": "--dry-run" not in args,
            "jobId": "same-notification",
            "swarmId": "original-swarm",
            "dailySlot": {
                "delegationId": "original-goal",
                "timezone": "Asia/Shanghai",
                "date": "2026-11-08",
                "slot": "morning",
            },
        }


def invoke(host, **kwargs):
    return wake(
        "project-a",
        "original-main",
        "original-swarm",
        "original-goal",
        "Asia/Shanghai",
        "morning",
        clock=datetime(2026, 11, 8, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        cli=host,
        **kwargs,
    )


@pytest.mark.parametrize("dry_run", [False, True])
def test_skill_uses_original_goal_host_command_without_user_text_or_new_session(
    dry_run,
):
    host = Host()
    result = invoke(host, dry_run=dry_run)
    assert result["state"] == ("prepared" if dry_run else "accepted")
    assert result["delivered"] is not dry_run
    command = host.calls[-1]
    assert command[command.index("--date") + 1] == "2026-11-08"
    assert command[command.index("--delegation") + 1] == "original-goal"
    assert not any(word in command for word in ["wake", "send", "new", "--file", "--prompt"])


def test_old_message_wake_capability_cannot_substitute_for_goal_entry():
    host = Host(supported=False)
    assert invoke(host, dry_run=True)["reason"] == "GOAL_DAILY_NOT_SUPPORTED"
    assert len(host.calls) == 1


@pytest.mark.parametrize(
    "changed",
    [
        {"kind": "home_main"},
        {"kind": "member"},
        {"projectId": "other"},
        {"conversationId": "other"},
        {"activeBranchId": ""},
    ],
)
def test_wrong_main_stops_before_any_notification(changed):
    host = Host(identity=changed)
    assert invoke(host)["reason"] == "PROJECT_MAIN_IDENTITY_MISMATCH"
    assert len(host.calls) == 2


@pytest.mark.parametrize("error", [CommandFailure(), subprocess.TimeoutExpired("roami", 45)])
def test_unknown_delivery_keeps_original_date_identity_and_does_not_retry(error):
    host = Host(final=error)
    result = invoke(host)
    assert result["state"] == "unknown" and result["delivered"] is None
    assert result["date"] == "2026-11-08" and result["delegationId"] == "original-goal"
    assert len(host.calls) == 3


@pytest.mark.parametrize(
    "code",
    [
        "SWARM_DAILY_DATE_EXPIRED",
        "SWARM_DELEGATION_SOURCE_STOPPED",
        "SWARM_DELEGATION_SOURCE_FORGOTTEN",
    ],
)
def test_terminal_host_refusal_is_not_publication_or_a_successful_wakeup(code):
    result = invoke(Host(final=CommandFailure(code)))
    assert result["state"] == "blocked" and result["reason"] == code
    assert result["delivered"] is False


def test_wrong_receipt_is_unknown_even_if_transport_succeeded():
    host = Host(
        final={
            "state": "accepted",
            "delivered": True,
            "jobId": "other",
            "swarmId": "another-project",
        }
    )
    assert invoke(host)["state"] == "unknown"


def test_recovery_keeps_explicit_old_date_instead_of_rolling_to_today():
    host = Host(final=CommandFailure("SWARM_DAILY_DATE_EXPIRED"))
    result = invoke(host, date="2026-11-07")
    assert result["date"] == "2026-11-07"
    args = host.calls[-1]
    assert args[args.index("--date") + 1] == "2026-11-07"


def test_agent_context_cannot_turn_its_own_output_into_a_daily_trigger(monkeypatch):
    monkeypatch.setenv("ROAMI_AGENT_TURN_ID", "member-turn")
    host = Host()
    assert invoke(host)["reason"] == "EXTERNAL_TRIGGER_REQUIRED"
    assert host.calls == []


def test_actual_cli_text_refusal_retains_only_its_bounded_code(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 1, "", "SWARM_DAILY_DATE_EXPIRED (HTTP 409) private-path-or-account"
        ),
    )
    with pytest.raises(CommandFailure) as raised:
        run_cli(["swarm", "daily", "original-swarm"])
    assert str(raised.value) == "SWARM_DAILY_DATE_EXPIRED"


def test_invalid_timezone_is_not_replaced_with_machine_timezone():
    with pytest.raises(ValueError, match="IANA timezone"):
        wake(
            "project-a",
            "original-main",
            "original-swarm",
            "original-goal",
            "Invalid/Zone",
            "morning",
            cli=Host(),
        )
