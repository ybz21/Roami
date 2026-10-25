"""Read-only process diagnostics independent of task workspaces."""

import asyncio
import math
import os
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.process import execute


def process_rows(output):
    processes, skipped = [], 0
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            pid, ppid, cpu, memory, rss, elapsed, command = line.split(None, 6)
            pid, ppid, rss = int(pid), int(ppid), int(rss)
            cpu, memory = float(cpu), float(memory)
            if (
                pid <= 0
                or ppid < 0
                or rss < 0
                or not all(math.isfinite(value) and value >= 0 for value in (cpu, memory))
            ):
                raise ValueError
        except ValueError:
            skipped += 1
            continue
        processes.append(
            {
                "pid": pid,
                "parentPid": ppid,
                "name": Path(command.strip()).name,
                "cpuPercent": cpu,
                "memoryPercent": memory,
                "rssBytes": rss * 1024,
                "elapsed": elapsed,
            }
        )
    return processes, skipped


def linux_memory():
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, value = line.split(":", 1)
            values[name] = int(value.split()[0]) * 1024
        total, available = values["MemTotal"], values["MemAvailable"]
        swap_total, swap_free = values["SwapTotal"], values["SwapFree"]
        if not (0 <= available <= total and 0 <= swap_free <= swap_total):
            return None
        return {
            "totalBytes": total,
            "availableBytes": available,
            "usedBytes": total - available,
            "swapTotalBytes": swap_total,
            "swapUsedBytes": swap_total - swap_free,
        }
    except (OSError, ValueError, KeyError, IndexError):
        return None


def register_host_processes(registry):
    async def snapshot(args, binding):
        try:
            result = await execute(
                ["ps", "-axo", "pid=,ppid=,pcpu=,pmem=,rss=,etime=,comm="],
                timeout=5,
                env={"PATH": os.defpath, "LC_ALL": "C"},
            )
        except (OSError, TimeoutError):
            raise DomainError("HOST_DIAGNOSTICS_UNAVAILABLE", 503) from None
        if result["exitCode"] != 0:
            raise DomainError("HOST_DIAGNOSTICS_UNAVAILABLE", 503)
        processes, skipped = process_rows(result["stdout"])
        if not processes:
            raise DomainError("HOST_DIAGNOSTICS_UNAVAILABLE", 503)
        memory = await asyncio.to_thread(linux_memory)
        try:
            load = list(os.getloadavg())
        except (AttributeError, OSError):
            load = None
        limit = args.get("limit", 10)
        return {
            "scope": "runtime_host",
            "observedAtMs": now_ms(),
            "cpuCount": os.cpu_count(),
            "cpuPercentBasis": "ps_lifetime_average_per_core",
            "loadAverage": load,
            "memory": memory,
            "processCount": len(processes),
            "skippedRows": skipped,
            "topCpu": sorted(processes, key=lambda p: (-p["cpuPercent"], p["pid"]))[:limit],
            "topMemory": sorted(processes, key=lambda p: (-p["rssBytes"], p["pid"]))[:limit],
            "unavailable": [
                name for name, value in (("memory", memory), ("loadAverage", load)) if value is None
            ],
        }

    registry.add(
        Tool(
            "host_processes",
            "Read current local machine process CPU/memory usage, load average, memory and swap. "
            "Returns top CPU and RSS processes with PID and elapsed time; ps CPU is a lifetime average per core, "
            "not an instantaneous sample. Runs on the Agent runtime host/namespace, not the user's phone or remote nodes. "
            "No workspace, project, shell argv or browser task required. Command names only; no arguments or environment. "
            "Unavailable metrics stay null. Read-only; cannot kill processes or modify the host.",
            object_schema({"limit": {"type": "integer", "minimum": 1, "maximum": 50}}),
            snapshot,
            main=True,
            cancellation_stops_execution=True,
        )
    )
