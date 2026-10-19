#!/usr/bin/env python3
"""Replay task-delivery production failures with isolated, deterministic fixtures."""

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/roami-task-delivery-benchmark.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    commands = [
        ("runtime", REPO / "agent-runtime", ["uv", "run", "--frozen", "pytest", "-q", "tests/test_task_delivery_benchmark.py", "tests/test_unlimited_execution.py", "tests/test_routing_policy.py", "tests/test_coding_executor.py", "tests/test_task_revisions.py"]),
        ("cli", REPO, ["go", "test", "./internal/agentexecution", "-run", "TestDeadlineRetainsPartialOutputForInspection|TestUnlimitedExecutionContextRemainsCancellable", "-count=1"]),
        ("ui", REPO / "frontend", ["npx", "vitest", "run", "src/components/agent/agent-tasks.test.tsx", "src/components/agent/agent-inbox.test.tsx", "src/components/agent/agent-workspace.test.tsx"]),
    ]
    result = {"startedAt": datetime.now(timezone.utc).isoformat(), "method": "deterministic fault injection; no live model score", "runs": []}
    for name, cwd, command in commands:
        started = time.monotonic()
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        log = args.output.with_name(args.output.stem + "-" + name + ".log")
        log.write_text(completed.stdout + completed.stderr)
        run = {"name": name, "command": command, "exitCode": completed.returncode, "passed": completed.returncode == 0, "durationSeconds": round(time.monotonic() - started, 3), "log": str(log)}
        result["runs"].append(run)
        print(name + ": " + ("PASS" if run["passed"] else "FAIL"), flush=True)
    result["passed"] = all(r["passed"] for r in result["runs"])
    result["manualBrowserAndAndroid"] = "record separately; this runner does not perform device acceptance"
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
