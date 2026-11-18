"""An explicitly shared runner proves the installed minute loop without dispatching jobs."""

import copy
import time

import pytest
from test_systemd_cron_runner import runner_case as runner_case_fixture

from roami_agent.protocol.errors import DomainError

runner_case = runner_case_fixture


@pytest.fixture
async def shared_case(runner_case):
    runner, props, calls = runner_case
    following = time.monotonic_ns() // 1000 + 60_000_000
    props["NextElapseUSecMonotonic"] = ("t", following)
    props["TimersMonotonic"] = (
        "a(stt)",
        [["OnUnitActiveUSec", 60_000_000, following], ["OnBootUSec", 120_000_000, 120_000_000]],
    )
    props["ExecStart"][1][0][1] = [runner.settings.cli_bin, "cron", "tick"]
    return runner, props, calls


async def test_shared_live_runner_requires_explicit_mode_and_only_reads(shared_case):
    runner, props, calls = shared_case
    before = copy.deepcopy(props)
    with pytest.raises(DomainError, match="GOAL_SCHEDULE_"):
        await runner.probe("project.timer", "project-morning", allow_short_command=True)
    proof = await runner.probe(
        "project.timer", "project-morning", allow_short_command=True, shared=True
    )
    assert proof["runnerScope"] == "shared"
    assert int(time.time() * 1000) < proof["nextTickMs"] <= int(time.time() * 1000) + 120000
    assert len(proof["execSha256"]) == 64
    assert props == before and all(call[0] in {"call", "get-property"} for call in calls)


@pytest.mark.parametrize(
    "fault",
    [
        "inactive",
        "service",
        "past",
        "distant",
        "wrong_type",
        "slow",
        "different_deadline",
        "unknown_timer",
        "duplicate",
        "malformed",
        "executable",
        "argv_executable",
        "scope",
        "shell",
        "ignored",
        "commands",
    ],
)
async def test_shared_runner_rejects_unverified_properties_or_commands(shared_case, fault):
    runner, props, _ = shared_case
    command = props["ExecStart"][1][0]
    if fault == "inactive":
        props["ActiveState"] = ("s", "inactive")
    elif fault == "service":
        props["Unit"] = ("s", "other.service")
    elif fault == "past":
        props["NextElapseUSecMonotonic"] = ("t", 1)
    elif fault == "distant":
        props["NextElapseUSecMonotonic"] = ("t", time.monotonic_ns() // 1000 + 121_000_000)
    elif fault == "wrong_type":
        props["NextElapseUSecMonotonic"] = ("s", "1")
    elif fault == "slow":
        props["TimersMonotonic"][1][0][1] = 61_000_000
    elif fault == "different_deadline":
        props["TimersMonotonic"][1][0][2] += 1
    elif fault == "unknown_timer":
        props["TimersMonotonic"][1][0][0] = "OnStartupUSec"
    elif fault == "duplicate":
        props["TimersMonotonic"][1][1] = copy.deepcopy(props["TimersMonotonic"][1][0])
    elif fault == "malformed":
        props["TimersMonotonic"] = ("a(stt)", [["OnUnitActiveUSec"]])
    elif fault == "executable":
        command[0] = "/usr/bin/sh"
    elif fault == "argv_executable":
        command[1][0] = "/usr/bin/sh"
    elif fault == "scope":
        command[1] += ["--name", "other-project"]
    elif fault == "shell":
        command[1] = [runner.settings.cli_bin, "shell", "cron tick"]
    elif fault == "ignored":
        command[2] = True
    elif fault == "commands":
        props["ExecStart"][1].append(copy.deepcopy(command))
    with pytest.raises(DomainError, match="GOAL_SCHEDULE_"):
        await runner.probe(
            "project.timer", "project-morning", allow_short_command=True, shared=True
        )


@pytest.mark.parametrize("name", ["cron.tick", "roam.cron:tick"])
async def test_shared_plugin_tick_aliases_preserve_exact_global_command(shared_case, name):
    runner, props, _ = shared_case
    props["ExecStart"][1][0][1] = [runner.settings.cli_bin, "plugin", "run", name]
    assert (
        await runner.probe(
            "project.timer", "project-morning", allow_short_command=True, shared=True
        )
    )["runnerScope"] == "shared"
