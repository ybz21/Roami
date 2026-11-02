"""Freeze the Go parent-lifetime proof and require every declared test event."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    case = Path(__file__).resolve().parents[1]
    repository = case.parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    tools = json.loads((case / "tools.json").read_text())
    files = {p for p in case.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    for folder in ["cmd", "internal", "backend", "agent-runtime"]:
        files.update(
            p for p in (repository / folder).rglob("*.go") if ".venv" not in p.parts
        )
    frozen = {str(p.relative_to(repository)): digest(p) for p in sorted(files)}
    (output / "frozen.json").write_text(json.dumps(frozen, indent=2) + "\n")
    launcher = repository / "scripts/dev/isolated-roami.sh"
    instance = output / "instance"
    with (output / "tests.log").open("w") as log:
        try:
            result = subprocess.run(
                [
                    str(launcher),
                    str(instance),
                    "go",
                    "test",
                    "-json",
                    tools["go_package"],
                    "-run",
                    tools["go_run"],
                    "-count=1",
                ],
                cwd=repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        finally:
            cleanup = subprocess.run(
                [str(launcher), str(instance), "--stop"],
                cwd=repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
    events = []
    for line in (output / "tests.log").read_text().splitlines():
        if line.startswith("{"):
            events.append(json.loads(line))
    terminal = [
        e
        for e in events
        if e.get("Test") and e.get("Action") in ["pass", "fail", "skip"]
    ]
    counts = {
        "tests": len(terminal),
        "failures": sum(e["Action"] == "fail" for e in terminal),
        "errors": 0,
        "skipped": sum(e["Action"] == "skip" for e in terminal),
    }
    unchanged = all(digest(repository / name) == sha for name, sha in frozen.items())
    passed = (
        result.returncode == cleanup.returncode == 0
        and unchanged
        and counts
        == {
            "tests": tools["expected_collected"],
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        }
        and {e["Test"] for e in terminal} == set(tools["test_names"])
    )
    receipt = {
        "case": "MECH-AP01",
        "passed": passed,
        "tests": counts,
        "exit_code": result.returncode,
        "cleanup_exit_code": cleanup.returncode,
        "implementation_unchanged": unchanged,
        "model_calls": 0,
        "historical_suite_updated": False,
        "scope": "foreground Runtime parent ownership; not business quality",
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
