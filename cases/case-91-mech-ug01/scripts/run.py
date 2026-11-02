"""Freeze the gateway sources and run local response and migration fixtures."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def snapshot(repository):
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=repository,
        )
        .decode()
        .split("\0")
    )
    return {
        name: hashlib.sha256((repository / name).read_bytes()).hexdigest()
        for name in names
        if (repository / name).is_file() and not (repository / name).is_symlink()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    folder = Path(__file__).resolve().parents[1]
    repository = folder.parents[1]
    if output == repository or repository in output.parents:
        parser.error("Output must be a new directory outside the checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    tools = json.loads((folder / "tools.json").read_text())
    assert (folder / "input/upstream-receipts.json").read_bytes() == (
        repository / tools["runtime_fixture"]
    ).read_bytes()
    frozen = snapshot(repository)
    (output / "frozen.json").write_text(json.dumps(frozen, indent=2) + "\n")
    launcher = repository / "scripts/dev/isolated-roami.sh"
    with (output / "tests.jsonl").open("w") as log:
        try:
            result = subprocess.run(
                [
                    str(launcher),
                    str(output / "instance"),
                    "go",
                    "test",
                    "-json",
                    "-count=1",
                    *tools["go_packages"],
                    "-run",
                    tools["go_test_pattern"],
                ],
                cwd=repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        finally:
            cleanup = subprocess.run(
                [str(launcher), str(output / "instance"), "--stop"],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            (output / "cleanup.log").write_text(cleanup.stdout + cleanup.stderr)
    events, unstructured = [], 0
    for line in (output / "tests.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            unstructured += 1
            continue
        if isinstance(event, dict) and isinstance(event.get("Action"), str):
            events.append(event)
        else:
            unstructured += 1
    tests = {e["Test"] for e in events if e["Action"] == "run" and "Test" in e}
    leaves = {
        name for name in tests if not any(n.startswith(name + "/") for n in tests)
    }
    passed_names = {e["Test"] for e in events if e["Action"] == "pass" and "Test" in e}
    counts = {
        "groups": sum("/" not in name for name in tests),
        "leaf_tests": len(leaves),
        "failures": sum(e["Action"] == "fail" for e in events),
        "skipped": sum(e["Action"] == "skip" for e in events),
        "unstructured_lines": unstructured,
    }
    unchanged = frozen == snapshot(repository)
    passed = (
        result.returncode == cleanup.returncode == 0
        and unchanged
        and counts
        == {
            "groups": tools["expected_groups"],
            "leaf_tests": tools["expected_leaf_tests"],
            "failures": 0,
            "skipped": 0,
            "unstructured_lines": 0,
        }
        and passed_names == tests
    )
    receipt = {
        "case": "MECH-UG01",
        "passed": passed,
        "checks": counts,
        "exit_code": result.returncode,
        "cleanup_exit_code": cleanup.returncode,
        "implementation_unchanged": unchanged,
        "external_model_calls": 0,
        "historical_suite_updated": False,
        "historical_401_root_cause_proven": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
