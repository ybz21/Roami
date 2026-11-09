"""An installed schedule must resolve to the original goal and a live scoped runner."""

import hashlib
import json
import shlex
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from roami_agent.executors.project_goal_schedule import DRIVER, ProjectGoalSchedule
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.workspace_files import WorkspaceFiles


@pytest.fixture
async def scheduled_project(tmp_path):
    root = tmp_path / "project space"
    plan = root / ".roami/okr/schedules/daily.json"
    plan.parent.mkdir(parents=True)
    scope = {
        "projectId": "project-a",
        "mainConversationId": "main-a",
        "swarmId": "swarm-a",
        "delegationId": "goal-a",
    }
    config = {
        "schemaVersion": 1,
        "enabled": True,
        **scope,
        "timezone": "Asia/Shanghai",
        "dailyAt": "09:00",
        "slots": ["morning"],
        "cron": "0 9 * * *",
        "schedulerPlugin": "cron",
        "schedulerJob": "project-a-morning",
        "runnerUnit": "project-a.timer",
    }
    plan.write_text(json.dumps(config))
    driver = root / DRIVER.removeprefix("assets/")
    driver.parent.mkdir(parents=True)
    driver.write_bytes(
        (Path(__file__).resolve().parents[2] / "skills/okr-development" / DRIVER).read_bytes()
    )
    cli = tmp_path / "bin/roami"
    cli.parent.mkdir()
    cli.write_text("fixture, never executed")
    cli.chmod(0o700)
    settings = SimpleNamespace(cli_bin=str(cli), provider_key_environments=list)
    files = WorkspaceFiles(settings)
    registry = SimpleNamespace(
        skills={
            "okr-development": {
                "source": "builtin",
                "references": {
                    DRIVER: {"version": hashlib.sha256(driver.read_bytes()).hexdigest()}
                },
            }
        }
    )

    async def workspace(project):
        assert project == "project-a"
        return {"projectId": project, "directory": str(root)}

    source = ProjectGoalSchedule(
        settings, SimpleNamespace(project_workspace=workspace), files, registry
    )
    now = datetime.now(ZoneInfo(config["timezone"]))
    due = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if due <= now:
        due += timedelta(days=1)
    command = f"PATH={cli.parent} /usr/bin/python3 {shlex.quote(str(driver))} " + " ".join(
        shlex.quote(x)
        for x in [
            "--project",
            "project-a",
            "--conversation",
            "main-a",
            "--swarm",
            "swarm-a",
            "--delegation",
            "goal-a",
            "--timezone",
            "Asia/Shanghai",
            "--slot",
            "morning",
        ]
    )
    job = {
        "name": config["schedulerJob"],
        "enabled": True,
        "action": "exec",
        "cron": config["cron"],
        "timezone": config["timezone"],
        "nextRunAt": due.strftime("%Y-%m-%d %H:%M:%S"),
        "command": command,
    }
    plugins = [{"manifest": {"id": "roam.cron", "name": "cron"}, "enabled": True}]
    calls = []

    async def query(*argv):
        calls.append(argv)
        if argv == ("plugin", "ls", "--json"):
            return plugins
        assert argv == ("plugin", "run", "roam.cron:list")
        return {"scopedScheduler": True, "jobs": [job]}

    async def runner(unit, name, **kwargs):
        assert unit == config["runnerUnit"] and name == job["name"]
        return {
            "unit": unit,
            "service": "project-a.service",
            "nextTickMs": int(now.timestamp() * 1000) + 60000,
            "execSha256": "a" * 64,
        }

    source.query, source.runner.probe = query, runner
    try:
        yield SimpleNamespace(
            source=source,
            scope=scope,
            config=config,
            plan=plan,
            driver=driver,
            job=job,
            plugins=plugins,
            calls=calls,
            root=root,
        )
    finally:
        await files.close()


async def test_existing_daily_job_is_read_only_and_returns_no_commands(scheduled_project):
    f = scheduled_project
    before = f.plan.read_bytes(), f.driver.read_bytes()
    proof = await f.source.read(f.scope)
    assert proof["projectId"] == "project-a" and proof["mainConversationId"] == "main-a"
    assert proof["jobName"] == "project-a-morning" and proof["slot"] == "morning"
    assert proof["nextDueMs"] > proof["observedAtMs"]
    assert int(datetime.fromisoformat(proof["nextRunAt"]).timestamp() * 1000) == proof["nextDueMs"]
    assert "command" not in proof and "directory" not in proof
    assert (f.plan.read_bytes(), f.driver.read_bytes()) == before
    assert f.calls == [("plugin", "ls", "--json"), ("plugin", "run", "roam.cron:list")]


@pytest.mark.parametrize(
    "fault",
    [
        "project",
        "main",
        "swarm",
        "goal",
        "timezone",
        "slot",
        "disabled",
        "past",
        "hour",
        "shell",
        "date",
        "shadow_cli",
        "no_path",
        "driver",
        "plugin_collision",
    ],
)
async def test_local_claims_and_wrong_or_changed_wakeup_do_not_authorize_wait(
    scheduled_project, fault, tmp_path
):
    f = scheduled_project
    swaps = {
        "project": ("project-a", "project-b"),
        "main": ("main-a", "main-b"),
        "swarm": ("swarm-a", "swarm-b"),
        "goal": ("goal-a", "goal-b"),
        "timezone": ("Asia/Shanghai", "UTC"),
        "slot": ("morning", "evening"),
    }
    if fault in swaps:
        f.job["command"] = f.job["command"].replace(*swaps[fault])
    elif fault == "disabled":
        f.job["enabled"] = False
    elif fault == "past":
        f.job["nextRunAt"] = "2000-01-01 09:00:00"
    elif fault == "hour":
        f.job["nextRunAt"] = f.job["nextRunAt"].replace("09:00:00", "08:00:00")
    elif fault == "shell":
        f.job["command"] += " ; touch " + shlex.quote(str(f.root / "never-run-this"))
    elif fault == "date":
        f.job["command"] += " --date 2099-01-01"
    elif fault == "no_path":
        f.job["command"] = f.job["command"].split(" ", 1)[1]
    elif fault == "shadow_cli":
        other = tmp_path / "shadow"
        other.mkdir()
        (other / "roami").write_text("not the trusted CLI")
        (other / "roami").chmod(0o700)
        f.job["command"] = f.job["command"].replace("PATH=", "PATH=" + str(other) + ":", 1)
    elif fault == "driver":
        f.driver.write_text("changed driver")
    elif fault == "plugin_collision":
        f.plugins.append({"manifest": {"name": "cron", "id": "other.cron"}, "enabled": False})
    with pytest.raises(DomainError, match="GOAL_SCHEDULE_"):
        await f.source.read(f.scope)
    assert not (f.root / "never-run-this").exists()


async def test_script_and_configuration_are_checked_again_after_live_probe(scheduled_project):
    f = scheduled_project

    async def changed(*args, **kwargs):
        f.plan.write_text(json.dumps({**f.config, "enabled": False}))
        return {
            "unit": "project-a.timer",
            "service": "project-a.service",
            "nextTickMs": 1,
            "execSha256": "a" * 64,
        }

    f.source.runner.probe = changed
    with pytest.raises(DomainError, match="GOAL_SCHEDULE_CHANGED"):
        await f.source.read(f.scope)
