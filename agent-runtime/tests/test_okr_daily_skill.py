import runpy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/okr-development/assets/.roami/okr/skills/daily-operations/scripts/wake_main.py"
)
waker = SimpleNamespace(**runpy.run_path(str(SCRIPT)))


class MainCLI:
    def __init__(self):
        self.calls = []
        self.identity = {
            "kind": "project_main",
            "projectId": "project",
            "conversationId": "main",
            "activeBranchId": "branch",
        }
        self.history = {
            "conversation": {"id": "main"},
            "branchId": "branch",
            "messages": [],
            "turns": [],
        }
        self.supported = True
        self.receipts = {}
        self.failure = None

    def __call__(self, args, text=None):
        self.calls.append((args, text))
        if args[0] == "status":
            return {"projectMainWake": self.supported}
        if args[0] == "identity":
            return self.identity
        if args[0] == "history":
            return self.history
        assert args[0] == "wake" and "send" not in args
        assert args[args.index("--conversation") + 1] == "main"
        assert args[args.index("--project") + 1] == "project"
        assert args[-2:] == ["--file", "-"]
        if self.failure:
            raise waker.CommandFailure(self.failure)
        key = args[args.index("--key") + 1]
        if key in self.receipts and self.receipts[key] != text:
            raise waker.CommandFailure("REQUEST_KEY_CONFLICT")
        self.receipts[key] = text
        return {"kind": "message", "messageId": "message", "turnId": "turn"}


@pytest.fixture(autouse=True)
def external_trigger(monkeypatch):
    monkeypatch.delenv("ROAMI_AGENT_CALLER_ROLE", raising=False)
    monkeypatch.delenv("ROAMI_AGENT_TURN_ID", raising=False)


def wake(cli, **kwargs):
    return waker.wake(
        "project",
        "main",
        "Asia/Shanghai",
        "kickoff",
        kwargs.pop("prompt", "Continue the existing team"),
        now=kwargs.pop("now", datetime(2026, 11, 5, 17, 30, tzinfo=UTC)),
        cli=cli,
        **kwargs,
    )


def test_same_day_slot_replays_one_message_and_prompt_edits_do_not_bypass_key():
    cli = MainCLI()
    first = wake(cli)
    assert first["state"] == "accepted" and first["date"] == "2026-11-06"
    assert wake(cli)["requestKey"] == first["requestKey"]
    assert len(cli.receipts) == 1
    changed = wake(cli, prompt="Change today's existing work")
    assert changed["state"] == "blocked" and changed["reason"] == "REQUEST_KEY_CONFLICT"
    assert len(cli.receipts) == 1
    following_day = wake(cli, now=datetime(2026, 11, 6, 17, 30, tzinfo=UTC))
    assert following_day["requestKey"] != first["requestKey"] and len(cli.receipts) == 2
    assert "不是账号或发布批准" in next(iter(cli.receipts.values()))


@pytest.mark.parametrize(
    "changed",
    [
        {"kind": "home_main"},
        {"kind": "member"},
        {"projectId": "other"},
        {"conversationId": "another"},
    ],
)
def test_never_wakes_a_home_member_or_other_project(changed):
    cli = MainCLI()
    cli.identity.update(changed)
    assert wake(cli)["state"] == "blocked"
    assert not cli.receipts
    assert not any(args[0] == "wake" for args, _ in cli.calls)


@pytest.mark.parametrize("state", ["queued", "running", "question"])
def test_running_or_waiting_main_is_not_interrupted(state):
    cli = MainCLI()
    if state == "question":
        cli.history["messages"] = [
            {"role": "assistant", "content": {"question": {"prompt": "Which account?"}}}
        ]
    else:
        cli.history["turns"] = [{"state": state}]
    assert wake(cli)["state"] == "deferred"
    assert not any(args[0] == "wake" for args, _ in cli.calls)


def test_busy_race_is_known_deferred_and_transport_failure_retains_same_key():
    cli = MainCLI()
    cli.failure = "MAIN_BUSY"
    assert wake(cli)["state"] == "deferred"
    cli.failure = "CLI_REQUEST_FAILED"
    unknown = wake(cli)
    assert unknown["state"] == "unknown" and unknown["delivered"] is None
    cli.failure = None
    accepted = wake(cli)
    assert accepted["requestKey"] == unknown["requestKey"] and len(cli.receipts) == 1


def test_old_runtime_supports_readonly_preparation_without_falling_back_to_send():
    cli = MainCLI()
    cli.supported = False
    prepared = wake(cli, dry_run=True)
    assert prepared["state"] == "prepared"
    assert prepared["supported"] is False and prepared["delivered"] is False
    blocked = wake(cli)
    assert blocked["state"] == "blocked" and blocked["reason"] == "MAIN_WAKE_NOT_SUPPORTED"
    assert not cli.receipts


def test_native_main_cannot_use_the_external_waker_to_wake_itself(monkeypatch):
    cli = MainCLI()
    monkeypatch.setenv("ROAMI_AGENT_CALLER_ROLE", "main")
    assert wake(cli)["reason"] == "EXTERNAL_TRIGGER_REQUIRED"
    assert not cli.calls


def test_invalid_timezone_is_not_silently_replaced_by_machine_timezone():
    with pytest.raises(ValueError, match="IANA timezone"):
        waker.wake("project", "main", "Invalid/Zone", "kickoff", "Continue", cli=MainCLI())
