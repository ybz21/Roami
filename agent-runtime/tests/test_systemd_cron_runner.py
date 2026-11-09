"""Typed node observations prove the live timer ticks only the selected cron job."""

import copy
import time
from types import SimpleNamespace

import pytest

from roami_agent.executors.systemd_cron_runner import SystemdCronRunner
from roami_agent.protocol.errors import DomainError


@pytest.fixture
def runner_case(tmp_path):
    cli = tmp_path / "roami"
    cli.write_text("fixture, never executed")
    cli.chmod(0o700)
    settings = SimpleNamespace(cli_bin=str(cli), provider_key_environments=list)
    runner = SystemdCronRunner(settings)
    tick = (int(time.time() * 1000) + 60000) * 1000
    props = {
        "ActiveState": ("s", "active"),
        "Unit": ("s", "project.service"),
        "NextElapseUSecRealtime": ("t", tick),
        "TimersCalendar": ("a(sst)", [["OnCalendar", "*-*-* *:*:00", tick]]),
        "ExecStart": (
            "a(sasbttttuii)",
            [
                [
                    str(cli),
                    [str(cli), "plugin", "run", "cron.tick", "--name", "project-morning"],
                    False,
                    0,
                    0,
                    0,
                    0,
                    1,
                    1,
                    0,
                ]
            ],
        ),
    }
    calls = []

    async def query(*args):
        calls.append(args)
        if args[0] == "call":
            name = args[-1].replace(".", "_2e")
            return {"type": "o", "data": ["/org/freedesktop/systemd1/unit/" + name]}
        assert args[0] == "get-property"
        signature, data = props[args[-1]]
        return {"type": signature, "data": copy.deepcopy(data)}

    runner.query = query
    return runner, props, calls


async def test_live_typed_timer_and_effective_argv_are_read_without_starting_services(runner_case):
    runner, _, calls = runner_case
    proof = await runner.probe("project.timer", "project-morning", allow_short_command=True)
    assert proof["unit"] == "project.timer" and proof["service"] == "project.service"
    assert len(proof["execSha256"]) == 64 and proof["nextTickMs"] > int(time.time() * 1000)
    assert all(call[0] in {"call", "get-property"} for call in calls)
    assert "argv" not in proof


@pytest.mark.parametrize(
    "fault",
    [
        "inactive",
        "other_service",
        "overdue",
        "slow_timer",
        "other_executable",
        "global_tick",
        "other_job",
        "extra_scope",
        "ignored_failure",
        "short_alias",
        "wrong_type",
    ],
)
async def test_unavailable_or_unscoped_runner_never_becomes_valid_wait(runner_case, fault):
    runner, props, _ = runner_case
    command = props["ExecStart"][1][0]
    if fault == "inactive":
        props["ActiveState"] = ("s", "inactive")
    elif fault == "other_service":
        props["Unit"] = ("s", "someone-else.service")
    elif fault == "overdue":
        props["NextElapseUSecRealtime"] = ("t", 1)
    elif fault == "slow_timer":
        props["TimersCalendar"] = ("a(sst)", [["OnCalendar", "*-*-* *:00:00", 1]])
    elif fault == "other_executable":
        command[0] = "/usr/bin/sh"
    elif fault == "global_tick":
        command[1] = command[1][:4]
    elif fault == "other_job":
        command[1][-1] = "someone-else"
    elif fault == "extra_scope":
        command[1][4:] = ["--names", '["project-morning","someone-else"]']
    elif fault == "ignored_failure":
        command[2] = True
    elif fault == "wrong_type":
        props["NextElapseUSecRealtime"] = ("s", str(props["NextElapseUSecRealtime"][1]))
    with pytest.raises(DomainError, match="GOAL_SCHEDULE_"):
        await runner.probe(
            "project.timer", "project-morning", allow_short_command=fault != "short_alias"
        )


async def test_qualified_command_and_single_named_list_keep_exact_scope(runner_case):
    runner, props, _ = runner_case
    command = props["ExecStart"][1][0]
    command[1][3:] = ["roam.cron:tick", "--names", '["project-morning"]']
    assert await runner.probe("project.timer", "project-morning", allow_short_command=False)
