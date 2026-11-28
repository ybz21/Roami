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


def schedule_entries(config):
    version = config["schemaVersion"]
    slots = config["slots"]
    if type(version) is not int or version not in {1, 2} or not isinstance(slots, list):
        raise ValueError
    if version == 1:
        if len(slots) != 1:
            raise ValueError
        slots = [
            {
                "slot": slots[0],
                "schedulerJob": config["schedulerJob"],
                "dailyAt": config["dailyAt"],
                "cron": config["cron"],
            }
        ]
    if not slots:
        raise ValueError
    entries = []
    for entry in slots:
        slot, job, daily_at = entry["slot"], entry["schedulerJob"], entry["dailyAt"]
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", slot)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", job)
            or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_at)
        ):
            raise ValueError
        hour, minute = map(int, daily_at.split(":"))
        cron = f"{minute} {hour} * * *"
        if entry.get("cron", cron) != cron:
            raise ValueError
        entries.append((slot, job, hour, minute, cron))
    if len({entry[0] for entry in entries}) != len(entries) or len(
        {entry[1] for entry in entries}
    ) != len(entries):
        raise ValueError
    return entries


def next_due(value, zone, hour, minute):
    date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    due = date.replace(tzinfo=zone)
    if (
        (date.hour, date.minute, date.second) != (hour, minute, 0)
        or due.utcoffset() != due.replace(fold=1).utcoffset()
        or due.astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None) != date
    ):
        raise ValueError
    return due


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
    def wake_command(command, root, scope, timezone, slot, cli_bin):
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
            "--timezone": timezone,
            "--slot": slot,
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
                config.get("enabled") is True
                and all(config.get(key) == value for key, value in scope.items())
                and config.get("schedulerPlugin") in {"cron", "roam.cron"}
            )
            if not valid:
                raise ValueError
            zone = ZoneInfo(config["timezone"])
            entries = schedule_entries(config)
            runner_scope = config.get("runnerScope", "project")
            if runner_scope not in {"project", "shared"}:
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
        due_slots = [
            self.verify_slot(jobs, entry, zone, root, scope, config["timezone"])
            for entry in entries
        ]
        due, slot, job = min(due_slots, key=lambda entry: (entry[0], entry[1]))
        due_ms = int(due.timestamp() * 1000)
        names = tuple(entry[1] for entry in entries)
        runner = await self.runner.probe(
            config.get("runnerUnit"),
            names[0] if len(names) == 1 else names,
            allow_short_command=True,
            **({"shared": True} if runner_scope == "shared" else {}),
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
            "slot": slot,
            "timezone": config["timezone"],
            "nextDueMs": due_ms,
            "nextRunAt": due.isoformat(),
            "scheduleSha256": digest(raw),
            "driverSha256": digest(driver),
            "commandSha256": digest(job["command"].encode()),
            **runner,
            "observedAtMs": int(time.time() * 1000),
        }

    def verify_slot(self, jobs, entry, zone, root, scope, timezone):
        slot, name, hour, minute, cron = entry
        selected = [job for job in jobs if isinstance(job, dict) and job.get("name") == name]
        if len(selected) != 1:
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        job = selected[0]
        if (
            job.get("enabled") is not True
            or job.get("action") != "exec"
            or job.get("timezone") != timezone
            or job.get("cron") != cron
        ):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        self.wake_command(job.get("command"), root, scope, timezone, slot, self.settings.cli_bin)
        try:
            due = next_due(job["nextRunAt"], zone, hour, minute)
        except (ValueError, TypeError, KeyError):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409) from None
        due_ms = int(due.timestamp() * 1000)
        now = int(time.time() * 1000)
        if not now < due_ms <= now + 26 * 3600000:
            raise DomainError("GOAL_SCHEDULE_NOT_FUTURE", 409)
        return due, slot, job
