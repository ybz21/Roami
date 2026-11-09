"""Verify an existing daily wakeup without executing its command or changing its schedule."""

import hashlib
import json
import re
import shlex
import shutil
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roami_agent.executors.systemd_cron_runner import SystemdCronRunner
from roami_agent.protocol.errors import DomainError
from roami_agent.tools.process import execute

DRIVER = "assets/.roami/okr/skills/daily-operations/scripts/wake_main.py"


def digest(body):
    return hashlib.sha256(body).hexdigest()


def schedule_identity(proof):
    return {key: value for key, value in proof.items() if key not in {"observedAtMs", "nextTickMs"}}


class ProjectGoalSchedule:
    def __init__(self, settings, targets, files, registry):
        self.settings, self.targets, self.files, self.registry = settings, targets, files, registry
        self.runner = SystemdCronRunner(settings)

    async def query(self, *args):
        try:
            result = await execute(
                [self.settings.cli_bin, *args],
                timeout=10,
                max_bytes=1_000_000,
                excluded_env=self.settings.provider_key_environments(),
            )
            if result["exitCode"]:
                raise ValueError
            return json.loads(result["stdout"])
        except (OSError, TimeoutError, ValueError, KeyError, DomainError):
            raise DomainError("GOAL_SCHEDULE_UNAVAILABLE", 503) from None

    def driver_digest(self):
        skill = self.registry.skills.get("okr-development", {})
        source = skill.get("references", {}).get(DRIVER, {})
        if skill.get("source") != "builtin" or not source.get("version"):
            raise DomainError("GOAL_SCHEDULE_DRIVER_UNAVAILABLE", 503)
        return source["version"]

    @staticmethod
    def wake_command(command, root, scope, config, cli_bin):
        if not isinstance(command, str):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        search_path = (
            argv[0][5:] if argv and re.fullmatch(r"PATH=[A-Za-z0-9_./:-]+", argv[0]) else ""
        )
        selected_cli = shutil.which("roami", path=search_path) if search_path else None
        trusted_cli = shutil.which(cli_bin)
        if (
            not selected_cli
            or not trusted_cli
            or any(not Path(p).is_absolute() for p in search_path.split(":"))
            or Path(selected_cli).resolve() != Path(trusted_cli).resolve()
        ):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        argv = argv[1:]
        if command.strip() != "PATH=" + search_path + " " + shlex.join(argv):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        if (
            len(argv) != 14
            or not shutil.which(argv[0])
            or Path(shutil.which(argv[0])).resolve() != Path("/usr/bin/python3").resolve()
            or argv[1] != str(root / ".roami/okr/skills/daily-operations/scripts/wake_main.py")
        ):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        expected = {
            "--project": scope["projectId"],
            "--conversation": scope["mainConversationId"],
            "--swarm": scope["swarmId"],
            "--delegation": scope["delegationId"],
            "--timezone": config["timezone"],
            "--slot": config["slots"][0],
        }
        pairs = list(zip(argv[2::2], argv[3::2], strict=True))
        if len(pairs) != len(expected) or dict(pairs) != expected:
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)

    async def read(self, scope):
        workspace = await self.targets.project_workspace(scope["projectId"])
        binding = {"workspace": workspace}
        root = Path(workspace["directory"])
        raw = await self.files.snapshot(".roami/okr/schedules/daily.json", binding, maximum=65536)
        try:
            config = json.loads(raw)
            valid = (
                type(config.get("schemaVersion")) is int
                and config["schemaVersion"] == 1
                and config.get("enabled") is True
                and all(config.get(key) == value for key, value in scope.items())
                and config.get("schedulerPlugin") in {"cron", "roam.cron"}
                and isinstance(config.get("schedulerJob"), str)
                and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", config["schedulerJob"]))
                and isinstance(config.get("slots"), list)
                and len(config["slots"]) == 1
                and isinstance(config["slots"][0], str)
                and bool(re.fullmatch(r"[a-z][a-z0-9-]{0,39}", config["slots"][0]))
                and bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", config.get("dailyAt", "")))
            )
            if not valid:
                raise ValueError
            zone = ZoneInfo(config["timezone"])
            hour, minute = map(int, config["dailyAt"].split(":"))
            cron = f"{minute} {hour} * * *"
            if config.get("cron") != cron:
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError, ZoneInfoNotFoundError):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409) from None
        script = ".roami/okr/skills/daily-operations/scripts/wake_main.py"
        driver = await self.files.snapshot(script, binding, maximum=65536)
        if digest(driver) != self.driver_digest():
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        plugins = await self.query("plugin", "ls", "--json")
        if not isinstance(plugins, list):
            raise DomainError("GOAL_SCHEDULE_UNAVAILABLE", 503)
        if any(not isinstance(p, dict) or not isinstance(p.get("manifest"), dict) for p in plugins):
            raise DomainError("GOAL_SCHEDULE_UNAVAILABLE", 503)
        owners = [p for p in plugins if p["manifest"].get("name") == "cron"]
        if (
            len(owners) != 1
            or owners[0]["manifest"].get("id") != "roam.cron"
            or owners[0].get("enabled") is not True
        ):
            raise DomainError("GOAL_SCHEDULE_UNAVAILABLE", 503)
        data = await self.query("plugin", "run", "roam.cron:list")
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list) or data.get("scopedScheduler") is not True:
            raise DomainError("GOAL_SCHEDULE_UNAVAILABLE", 503)
        selected = [
            job
            for job in jobs
            if isinstance(job, dict) and job.get("name") == config["schedulerJob"]
        ]
        if len(selected) != 1:
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        job = selected[0]
        if (
            job.get("enabled") is not True
            or job.get("action") != "exec"
            or job.get("timezone") != config["timezone"]
            or job.get("cron") != cron
        ):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        self.wake_command(job.get("command"), root, scope, config, self.settings.cli_bin)
        try:
            date = datetime.strptime(job["nextRunAt"], "%Y-%m-%d %H:%M:%S")
            if (date.hour, date.minute, date.second) != (hour, minute, 0):
                raise ValueError
            due = date.replace(tzinfo=zone)
            if (
                due.utcoffset() != due.replace(fold=1).utcoffset()
                or due.astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None) != date
            ):
                raise ValueError
            due_ms = int(due.timestamp() * 1000)
        except (ValueError, TypeError, KeyError):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409) from None
        if not int(time.time() * 1000) < due_ms <= int(time.time() * 1000) + 26 * 3600000:
            raise DomainError("GOAL_SCHEDULE_NOT_FUTURE", 409)
        runner = await self.runner.probe(
            config.get("runnerUnit"), job["name"], allow_short_command=True
        )
        if (
            await self.targets.project_workspace(scope["projectId"]) != workspace
            or await self.files.snapshot(".roami/okr/schedules/daily.json", binding, maximum=65536)
            != raw
            or await self.files.snapshot(script, binding, maximum=65536) != driver
        ):
            raise DomainError("GOAL_SCHEDULE_CHANGED", 409)
        if due_ms <= int(time.time() * 1000):
            raise DomainError("GOAL_SCHEDULE_NOT_FUTURE", 409)
        return {
            "kind": "registered_goal_schedule",
            **scope,
            "jobName": job["name"],
            "slot": config["slots"][0],
            "timezone": config["timezone"],
            "nextDueMs": due_ms,
            "nextRunAt": due.isoformat(),
            "scheduleSha256": digest(raw),
            "driverSha256": digest(driver),
            "commandSha256": digest(job["command"].encode()),
            **runner,
            "observedAtMs": int(time.time() * 1000),
        }
