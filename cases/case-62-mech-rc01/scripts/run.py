"""Run this extension Case without changing the frozen authored or formal suites."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def source_snapshot(repository):
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
        if name.endswith((".go", ".py", ".sh", ".toml", ".json"))
        and (repository / name).is_file()
        and not (repository / name).is_symlink()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository", type=Path, default=Path(__file__).resolve().parents[3]
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve(strict=True)
    output = args.output.resolve()
    if output.is_relative_to(repository):
        raise ValueError("Use a new output directory outside the checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    folder = Path(__file__).resolve().parents[1]
    tools = json.loads((folder / "tools.json").read_text())
    fixture = repository / tools["pytest_fixture"]
    canonical = folder / "input/receipts.json"
    if fixture.read_bytes() != canonical.read_bytes():
        raise ValueError("The regression test fixture does not match this Case input")
    resources = {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    implementation = source_snapshot(repository)
    (output / "frozen-case.json").write_text(
        json.dumps(
            {
                "contract": json.loads((folder / "case.json").read_text()),
                "display": (folder / "CASE.md").read_text(),
                "resource_sha256": resources,
                "repository_head": source,
                "implementation_sha256": implementation,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    (output / "started.json").write_text(
        json.dumps({"case": "MECH-RC01", "model_calls": 0}) + "\n"
    )
    launcher = repository / "scripts/dev/isolated-roami.sh"
    commands = [
        (
            "go",
            [
                "go",
                "test",
                "-json",
                "-count=1",
                *tools["go_packages"],
                "-run",
                tools["go_test_pattern"],
            ],
        ),
        (
            "python",
            [
                "uv",
                "run",
                "--frozen",
                "--project",
                "agent-runtime",
                "python",
                str(Path(__file__).resolve()),
                "--pytest-receipt",
                str(output / "pytest-receipt.json"),
                "-q",
                *["agent-runtime/" + s for s in tools["pytest_selectors"]],
            ],
        ),
    ]
    results = []
    environment = dict(os.environ)
    try:
        for name, command in commands:
            result = subprocess.run(
                [str(launcher), str(output / "instance"), *command],
                cwd=repository,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            (output / (name + ".log")).write_text(result.stdout + result.stderr)
            results.append(
                {
                    "kind": name,
                    "exit_code": result.returncode,
                    "skipped": " skipped" in result.stdout
                    or "--- SKIP:" in result.stdout,
                }
            )
            if result.returncode:
                break
    finally:
        cleanup = subprocess.run(
            [str(launcher), str(output / "instance"), "--stop"],
            cwd=repository,
            text=True,
            capture_output=True,
            check=False,
        )
        (output / "cleanup.log").write_text(cleanup.stdout + cleanup.stderr)
    source_unchanged = implementation == source_snapshot(repository)
    python_receipt = (
        json.loads((output / "pytest-receipt.json").read_text())
        if (output / "pytest-receipt.json").exists()
        else {}
    )
    go_events = [
        json.loads(line)
        for line in (output / "go.log").read_text().splitlines()
        if line.startswith("{")
    ]
    go_executed = any(
        item.get("Action") == "pass"
        and item.get("Test") == "TestHTTPFailuresUnknownUsageAndNoRedirect"
        for item in go_events
    ) and not any(item.get("Action") == "skip" for item in go_events)
    all_python_executed = (
        python_receipt.get("collected")
        == python_receipt.get("passed")
        == tools["pytest_expected_count"]
        and python_receipt.get("skipped") == 0
    )
    passed = (
        len(results) == len(commands)
        and all(r["exit_code"] == 0 and not r["skipped"] for r in results)
        and cleanup.returncode == 0
        and source_unchanged
        and go_executed
        and all_python_executed
    )
    receipt = {
        "case": "MECH-RC01",
        "scope": "deterministic mechanism regression, not a formal model score",
        "passed": passed,
        "checks": results,
        "cleanup_exit_code": cleanup.returncode,
        "model_calls": 0,
        "historical_suite_updated": False,
        "implementation_unchanged": source_unchanged,
        "go_contract_executed": go_executed,
        "pytest_receipt": python_receipt,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return 0 if passed else 1


def run_pytest(receipt_path, argv):
    import pytest

    class Receipt:
        def __init__(self):
            self.collected, self.skipped, self.passed = 0, 0, set()

        def pytest_collection_finish(self, session):
            self.collected = len(session.items)

        def pytest_runtest_logreport(self, report):
            if report.skipped or hasattr(report, "wasxfail"):
                self.skipped += 1
            if (
                report.when == "call"
                and report.passed
                and not hasattr(report, "wasxfail")
            ):
                self.passed.add(report.nodeid)

    receipt = Receipt()
    result = pytest.main(argv, plugins=[receipt])
    receipt_path.write_text(
        json.dumps(
            {
                "collected": receipt.collected,
                "passed": len(receipt.passed),
                "skipped": receipt.skipped,
            }
        )
        + "\n"
    )
    return result


if __name__ == "__main__":
    if sys.argv[1:2] == ["--pytest-receipt"]:
        sys.exit(run_pytest(Path(sys.argv[2]), sys.argv[3:]))
    sys.exit(main())
