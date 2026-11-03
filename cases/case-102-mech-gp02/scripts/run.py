"""Freeze and run the local gateway and report-display controls."""

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
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
        for name in sorted(set(names))
        if (repository / name).is_file() and not (repository / name).is_symlink()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1]
    repository, output = folder.parents[1], args.output.resolve()
    if output == repository or output.is_relative_to(repository):
        parser.error("Output must be a new directory outside the checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    frozen = snapshot(repository)
    (output / "frozen.json").write_text(json.dumps(frozen, indent=2) + "\n")
    tools = json.loads((folder / "tools.json").read_text())
    launcher = repository / "scripts/dev/isolated-roami.sh"
    try:
        with (output / "python.log").open("w") as log:
            backend = subprocess.run(
                [
                    str(launcher),
                    str(output / "instance"),
                    str(args.python.absolute()),
                    "-m",
                    "pytest",
                    "-q",
                    tools["python_test"],
                    "--junitxml=" + str(output / "python.xml"),
                ],
                cwd=repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        with (output / "frontend.log").open("w") as log:
            frontend = subprocess.run(
                [
                    str(launcher),
                    str(output / "instance"),
                    str(repository / "frontend/node_modules/.bin/vitest"),
                    "run",
                    tools["frontend_test"],
                    "--reporter=json",
                    "--outputFile=" + str(output / "frontend.json"),
                ],
                cwd=repository / "frontend",
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
    try:
        tests = list(ET.parse(output / "python.xml").getroot().iter("testcase"))
    except (OSError, ET.ParseError):
        tests = []
    failures = sum(
        any(t.find(tag) is not None for tag in ("failure", "error", "skipped"))
        for t in tests
    )
    try:
        ui = json.loads((output / "frontend.json").read_text())
    except (OSError, ValueError):
        ui = {}
    unchanged = snapshot(repository) == frozen
    passed = (
        backend.returncode == frontend.returncode == cleanup.returncode == failures == 0
        and len(tests) == tools["expected_python_tests"]
        and ui.get("success") is True
        and ui.get("numPassedTests")
        == ui.get("numTotalTests")
        == tools["expected_frontend_tests"]
        and ui.get("numPendingTests") == ui.get("numTodoTests") == 0
        and unchanged
    )
    receipt = {
        "case": "MECH-GP02",
        "passed": passed,
        "python_tests": len(tests),
        "python_failed_or_skipped": failures,
        "frontend_passed": ui.get("numPassedTests"),
        "frontend_total": ui.get("numTotalTests"),
        "source_unchanged": unchanged,
        "external_model_calls": 0,
        "historical_suite_updated": False,
        "mobile_acceptance_separate": True,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
