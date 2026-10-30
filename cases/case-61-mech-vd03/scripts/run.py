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
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    folder = Path(__file__).resolve().parents[1]
    tools = json.loads((folder / "tools.json").read_text())
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
        json.dumps({"case": "MECH-VD03", "model_calls": 0}) + "\n"
    )
    launcher = repository / "scripts/dev/isolated-roami.sh"
    commands = [
        (
            "go",
            [
                "go",
                "test",
                "-v",
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
                "--project",
                "agent-runtime",
                "pytest",
                "-q",
                *["agent-runtime/" + s for s in tools["pytest_selectors"]],
            ],
        ),
    ]
    results = []
    environment = dict(
        os.environ, ROAMI_CASE61_INPUT=str(folder / "input/incident.json")
    )
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
    passed = (
        len(results) == len(commands)
        and all(r["exit_code"] == 0 and not r["skipped"] for r in results)
        and cleanup.returncode == 0
        and source_unchanged
    )
    receipt = {
        "case": "MECH-VD03",
        "scope": "deterministic mechanism regression, not a formal model score",
        "passed": passed,
        "checks": results,
        "cleanup_exit_code": cleanup.returncode,
        "model_calls": 0,
        "historical_suite_updated": False,
        "implementation_unchanged": source_unchanged,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
