"""Read typed systemd properties for an existing, project-scoped cron tick timer."""

import asyncio
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.tools.process import execute

BUS = "org.freedesktop.systemd1"


class SystemdCronRunner:
    def __init__(self, settings):
        self.settings = settings

    async def query(self, *arguments):
        try:
            result = await execute(
                ["busctl", "--user", "--json=short", *arguments],
                timeout=5,
                max_bytes=16000,
                excluded_env=self.settings.provider_key_environments(),
            )
            if result["exitCode"]:
                raise ValueError
            data = json.loads(result["stdout"])
            if not isinstance(data, dict):
                raise TypeError
            return data
        except (OSError, TimeoutError, ValueError, TypeError, KeyError, DomainError):
            raise DomainError("GOAL_SCHEDULE_RUNNER_UNAVAILABLE", 503) from None

    async def unit_path(self, unit):
        result = await self.query(
            "call", BUS, "/org/freedesktop/systemd1", BUS + ".Manager", "GetUnit", "s", unit
        )
        data = result.get("data")
        if (
            result.get("type") != "o"
            or not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], str)
            or not re.fullmatch(r"/org/freedesktop/systemd1/unit/[A-Za-z0-9_]+", data[0])
        ):
            raise DomainError("GOAL_SCHEDULE_RUNNER_UNAVAILABLE", 503)
        return data[0]

    async def property(self, path, interface, name, signature):
        result = await self.query("get-property", BUS, path, BUS + "." + interface, name)
        if result.get("type") != signature:
            raise DomainError("GOAL_SCHEDULE_RUNNER_UNAVAILABLE", 503)
        return result.get("data")

    async def probe(self, unit, job, *, allow_short_command):
        if not isinstance(unit, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.timer", unit
        ):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        path = await self.unit_path(unit)
        state, service, next_tick, calendars = await asyncio.gather(
            self.property(path, "Unit", "ActiveState", "s"),
            self.property(path, "Timer", "Unit", "s"),
            self.property(path, "Timer", "NextElapseUSecRealtime", "t"),
            self.property(path, "Timer", "TimersCalendar", "a(sst)"),
        )
        now = int(time.time() * 1000)
        if (
            state != "active"
            or service != unit.removesuffix(".timer") + ".service"
            or type(next_tick) is not int
            or not now < next_tick // 1000 <= now + 120000
            or not isinstance(calendars, list)
            or len(calendars) != 1
            or not isinstance(calendars[0], list)
            or len(calendars[0]) != 3
            or calendars[0][:2] != ["OnCalendar", "*-*-* *:*:00"]
            or calendars[0][2] != next_tick
        ):
            raise DomainError("GOAL_SCHEDULE_RUNNER_UNAVAILABLE", 503)
        service_path = await self.unit_path(service)
        commands = await self.property(service_path, "Service", "ExecStart", "a(sasbttttuii)")
        valid = isinstance(commands, list) and len(commands) == 1
        command = commands[0] if valid else None
        valid = valid and isinstance(command, list) and len(command) == 10
        executable, argv, ignored = command[:3] if valid else (None, None, None)
        cli = shutil.which(self.settings.cli_bin)
        if (
            not cli
            or not isinstance(executable, str)
            or Path(executable).resolve() != Path(cli).resolve()
            or not isinstance(argv, list)
            or not all(isinstance(item, str) for item in argv)
            or len(argv) < 4
            or Path(argv[0]).resolve() != Path(cli).resolve()
            or argv[1:3] != ["plugin", "run"]
            or argv[3]
            not in ({"roam.cron:tick", "cron.tick"} if allow_short_command else {"roam.cron:tick"})
            or ignored is not False
        ):
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        scope = argv[4:]
        if scope[:1] == ["--names"] and len(scope) == 2:
            try:
                valid = json.loads(scope[1]) == [job]
            except ValueError:
                valid = False
        else:
            valid = scope == ["--name", job]
        if not valid:
            raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
        if await self.property(path, "Unit", "ActiveState", "s") != "active":
            raise DomainError("GOAL_SCHEDULE_RUNNER_UNAVAILABLE", 503)
        return {
            "unit": unit,
            "service": service,
            "nextTickMs": next_tick // 1000,
            "execSha256": hashlib.sha256(encoded(command[:3]).encode()).hexdigest(),
        }
