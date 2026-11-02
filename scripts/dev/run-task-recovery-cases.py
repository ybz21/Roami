#!/usr/bin/env python3
"""Freeze task recovery inputs and require complete isolated test receipts."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
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


def pytest_receipt(path, expected):
    cases = list(ET.parse(path).getroot().iter("testcase"))
    actual = [
        item.attrib["classname"].rsplit(".", 1)[-1] + "." + item.attrib["name"]
        for item in cases
    ]
    identities = [
        Path(item.split("::", 1)[0]).stem + "." + item.split("::", 1)[1]
        for item in expected
    ]
    counts = {
        "tests": len(cases),
        "failures": sum(item.find("failure") is not None for item in cases),
        "errors": sum(item.find("error") is not None for item in cases),
        "skipped": sum(item.find("skipped") is not None for item in cases),
    }
    return {
        **counts,
        "identities_match": bool(expected) and sorted(actual) == sorted(identities),
        "passed": bool(expected)
        and sorted(actual) == sorted(identities)
        and not any(counts[key] for key in ("failures", "errors", "skipped")),
    }


def go_receipt(path, expected):
    events = [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]
    started = [
        event["Test"]
        for event in events
        if event.get("Action") == "run" and "Test" in event
    ]
    passed = [
        event["Test"]
        for event in events
        if event.get("Action") == "pass" and "Test" in event
    ]
    failures = sum(event.get("Action") in {"fail", "skip"} for event in events)
    packages = [
        event
        for event in events
        if event.get("Action") == "pass" and "Test" not in event
    ]
    return {
        "groups": sum("/" not in name for name in started),
        "leaf_tests": sum(
            not any(other.startswith(name + "/") for other in started)
            for name in started
        ),
        "failures_or_skips": failures,
        "identities_match": sorted(started) == sorted(expected),
        "passed": bool(expected)
        and sorted(started) == sorted(passed) == sorted(expected)
        and failures == 0
        and len(packages) == 1,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case", choices=["MECH-TF01", "MECH-SI01", "MECH-TC01"], required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output == repository or (
        repository in output.parents and repository / ".roami" not in output.parents
    ):
        parser.error(
            "Use a new directory outside the checkout or below its ignored .roami directory"
        )
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    folders = list((repository / "cases").glob("case-*-" + args.case.lower()))
    if len(folders) != 1:
        parser.error("Case directory must be unique")
    folder = folders[0]
    scenarios = json.loads((folder / "input/scenarios.json").read_text())
    frozen = snapshot(repository)
    (output / "frozen.json").write_text(json.dumps(frozen, indent=2) + "\n")
    launcher = repository / "scripts/dev/isolated-roami.sh"
    instance = output / "instance"
    commands = []
    checks = {}
    error = None
    cleanup_code = None
    try:
        with tempfile.TemporaryDirectory(prefix="roami-recovery-") as scratch:
            python_command = [
                str(launcher),
                str(instance),
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-o",
                "xfail_strict=true",
                "--junitxml",
                str(output / "junit.xml"),
                "--basetemp",
                str(Path(scratch) / "pytest"),
                *scenarios["pytest_selectors"],
            ]
            with (output / "pytest.log").open("w") as log:
                result = subprocess.run(
                    python_command,
                    cwd=repository,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            commands.append({"kind": "pytest", "exit_code": result.returncode})
            checks["pytest"] = pytest_receipt(
                output / "junit.xml", scenarios["expected_pytest_ids"]
            )
            if scenarios["expected_go_tests"]:
                roots = [
                    name for name in scenarios["expected_go_tests"] if "/" not in name
                ]
                command = [
                    str(launcher),
                    str(instance),
                    "go",
                    "test",
                    "-json",
                    "-count=1",
                    "./internal/agentexecution",
                    "-run",
                    "^(" + "|".join(map(re.escape, roots)) + ")$",
                ]
                with (
                    (output / "go.jsonl").open("w") as log,
                    (output / "go.stderr").open("w") as stderr,
                ):
                    result = subprocess.run(
                        command, cwd=repository, stdout=log, stderr=stderr, check=False
                    )
                commands.append({"kind": "go", "exit_code": result.returncode})
                checks["go"] = go_receipt(
                    output / "go.jsonl", scenarios["expected_go_tests"]
                )
    except (OSError, ValueError, KeyError, ET.ParseError) as failure:
        error = type(failure).__name__
    finally:
        with (output / "cleanup.log").open("w") as log:
            cleanup = subprocess.run(
                [str(launcher), str(instance), "--stop"],
                cwd=repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
            cleanup_code = cleanup.returncode
    unchanged = frozen == snapshot(repository)
    passed = (
        error is None
        and bool(checks)
        and all(item["passed"] for item in checks.values())
        and all(item["exit_code"] == 0 for item in commands)
        and cleanup_code == 0
        and unchanged
    )
    receipt = {
        "case": args.case,
        "passed": passed,
        "checks": checks,
        "commands": commands,
        "error_type": error,
        "cleanup_exit_code": cleanup_code,
        "implementation_unchanged": unchanged,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository
        )
        .decode()
        .strip(),
        "frozen_sha256": hashlib.sha256(
            (output / "frozen.json").read_bytes()
        ).hexdigest(),
        "external_model_calls": 0,
        "historical_suite_updated": False,
        "scope": "Synthetic protocol and process fixtures; not production replay or drawing-model acceptance",
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
