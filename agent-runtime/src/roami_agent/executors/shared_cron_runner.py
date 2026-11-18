"""Observe the existing shared minute runner without ticking or changing any job."""

import asyncio
import hashlib
import shutil
import time
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded


async def observe_shared_runner(runner, unit):
    path = await runner.unit_path(unit)
    state, service, following, timers = await asyncio.gather(
        runner.property(path, "Unit", "ActiveState", "s"),
        runner.property(path, "Timer", "Unit", "s"),
        runner.property(path, "Timer", "NextElapseUSecMonotonic", "t"),
        runner.property(path, "Timer", "TimersMonotonic", "a(stt)"),
    )
    now_mono = time.monotonic_ns() // 1000
    now_wall = int(time.time() * 1000)
    valid = (
        state == "active"
        and service == unit.removesuffix(".timer") + ".service"
        and type(following) is int
        and 0 < following - now_mono <= 120_000_000
        and isinstance(timers, list)
        and 1 <= len(timers) <= 2
    )
    names = set()
    periodic = False
    for timer in timers if valid else []:
        if (
            not isinstance(timer, list)
            or len(timer) != 3
            or not isinstance(timer[0], str)
            or timer[0] not in {"OnUnitActiveUSec", "OnBootUSec"}
            or timer[0] in names
            or type(timer[1]) is not int
            or type(timer[2]) is not int
            or not 0 < timer[1] <= (60_000_000 if timer[0] == "OnUnitActiveUSec" else 120_000_000)
        ):
            valid = False
            break
        names.add(timer[0])
        periodic |= timer[0] == "OnUnitActiveUSec" and timer[2] == following
    if not valid or not periodic:
        raise DomainError("GOAL_SCHEDULE_RUNNER_UNAVAILABLE", 503)
    service_path = await runner.unit_path(service)
    commands = await runner.property(service_path, "Service", "ExecStart", "a(sasbttttuii)")
    command = commands[0] if isinstance(commands, list) and len(commands) == 1 else None
    if not isinstance(command, list) or len(command) != 10:
        raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
    executable, argv, ignored = command[:3]
    cli = shutil.which(runner.settings.cli_bin)
    if (
        not cli
        or not isinstance(executable, str)
        or Path(executable).resolve() != Path(cli).resolve()
        or not isinstance(argv, list)
        or len(argv) < 3
        or not all(isinstance(item, str) for item in argv)
        or Path(argv[0]).resolve() != Path(cli).resolve()
        or tuple(argv[1:])
        not in {
            ("cron", "tick"),
            ("plugin", "run", "cron.tick"),
            ("plugin", "run", "roam.cron:tick"),
        }
        or ignored is not False
    ):
        raise DomainError("GOAL_SCHEDULE_CONFIGURATION_CONFLICT", 409)
    if (
        await runner.property(path, "Unit", "ActiveState", "s") != "active"
        or following <= time.monotonic_ns() // 1000
    ):
        raise DomainError("GOAL_SCHEDULE_RUNNER_UNAVAILABLE", 503)
    return {
        "unit": unit,
        "service": service,
        "nextTickMs": now_wall + (following - now_mono) // 1000,
        "execSha256": hashlib.sha256(encoded(command[:3]).encode()).hexdigest(),
        "runnerScope": "shared",
    }
