#!/usr/bin/env python3
"""Run frozen conversation fixtures or the node's saved Main against an isolated task world."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from roami_agent.improvement.entrypoints.node_models import node_model_settings
from roami_agent.improvement.evaluation.conversation_scenarios import run_conversation
from roami_agent.providers.factory import configured_provider

CASES = ["CHAT-STACK01", "TASK-NEW01", "TASK-STACK01", "TASK-SCOPE01"]
REPOSITORY = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)


def snapshot():
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=REPOSITORY,
        )
        .decode()
        .split("\0")
    )
    return {
        name: hashlib.sha256((REPOSITORY / name).read_bytes()).hexdigest()
        for name in sorted(set(names))
        if (REPOSITORY / name).is_file() and not (REPOSITORY / name).is_symlink()
    }


def private_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def select(args):
    cases = []
    for ident in CASES if args.case == "all" else [args.case]:
        (folder,) = (REPOSITORY / "cases").glob("case-*-" + ident.lower())
        value = json.loads((folder / "input/conversations.json").read_text())
        selected = [
            s
            for s in value["scenarios"]
            if not args.scenario or s["id"] in args.scenario
        ]
        if selected:
            cases.append(
                {
                    "id": ident,
                    "scenarios": selected,
                    "complete_case": len(selected) == len(value["scenarios"]),
                }
            )
    if (
        not cases
        or args.scenario
        and set(args.scenario) != {s["id"] for c in cases for s in c["scenarios"]}
    ):
        raise ValueError("Unknown or out-of-scope conversation selection")
    return cases


async def episodes(args, cases):
    results, settings, provider, failure = [], None, None, None
    route_hash = None
    unaccounted_episode = False
    try:
        if args.mode == "saved-model":
            settings = await node_model_settings(args.agent_config, args.data_root)
            route = settings.route("main")
            route_hash = hashlib.sha256(
                json.dumps(
                    {
                        "model": route.name,
                        "parameters": route.parameters,
                        "capabilities": route.capabilities,
                        "cache": route.cache,
                        "context_window": route.context_window,
                        "retries": route.max_retries,
                        "timeout_seconds": route.timeout_seconds,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            provider = configured_provider(settings, "main")
        stopped = False
        for case in cases:
            for scenario in case["scenarios"]:
                if stopped:
                    break
                unaccounted_episode = True
                result = await run_conversation(
                    scenario,
                    args.output / scenario["id"],
                    settings=settings,
                    provider=provider,
                    review_replies=args.mode == "saved-model",
                )
                unaccounted_episode = False
                results.append({"case": case["id"], **result})
                stopped = (
                    bool(result["failure"])
                    or result["metrics"]["token_coverage"] != "complete"
                )
            if stopped:
                break
    except Exception as error:
        log.exception("Conversation evaluation stopped")
        failure = getattr(error, "code", type(error).__name__)
    finally:
        if provider:
            await provider.close()
        private_json(
            args.output / "episodes.json",
            {
                "results": results,
                "failure": failure,
                "saved_main_route_hash": route_hash,
                "usage_known": not unaccounted_episode,
            },
        )
    return 0 if results and not failure and all(r["passed"] for r in results) else 1


def execution_summary(evaluated):
    results = evaluated["results"]
    metrics = [r["metrics"] for r in results]
    process_complete = (
        not evaluated.get("failure")
        and evaluated.get("usage_known", True)
        and bool(metrics)
        and all(m.get("tool_process_coverage") == "complete" for m in metrics)
    )
    calls = sum(m.get("tool_calls", 0) for m in metrics)
    errors = sum(m.get("tool_errors", 0) for m in metrics)
    first_calls = sum(m.get("tool_first_calls", 0) for m in metrics)
    first_successes = sum(m.get("tool_first_successes", 0) for m in metrics)
    return {
        "tool_process_coverage": "complete" if process_complete else "partial",
        "tool_calls": calls,
        "tool_errors": errors,
        "tool_error_rate": errors / calls if process_complete and calls else None,
        "tool_first_attempt_success_rate": first_successes / first_calls
        if process_complete and first_calls
        else None,
        "failure": evaluated["failure"]
        or next((r["failure"] for r in results if r["failure"]), None),
        "blocked_scenarios": sum(r["state"] == "blocked" for r in results),
        "failed_scenarios": sum(r["state"] == "failed" for r in results),
        "semantic_checked_user_turns": sum(
            c["semantic_checked"] for r in results for c in r["checkpoints"]
        ),
        "live_model_semantics_tested": any(r["live_model_semantics_tested"] for r in results),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["all", *CASES], default="all")
    parser.add_argument("--mode", choices=["fixture", "saved-model"], default="fixture")
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-config", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--isolated-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.mode == "saved-model" and not (args.agent_config and args.data_root):
        parser.error("saved-model requires the node's saved agent config and data root")
    args.output = args.output.resolve()
    cases = select(args)
    launcher = REPOSITORY / "scripts/dev/isolated-roami.sh"
    instance = args.output / "instance"
    if args.isolated_child:
        subprocess.run([str(launcher), str(instance), "--verify"], check=True)
        raise SystemExit(asyncio.run(episodes(args, cases)))
    if args.output == REPOSITORY or (
        REPOSITORY in args.output.parents
        and REPOSITORY / ".roami" not in args.output.parents
    ):
        parser.error(
            "Use a new directory outside the checkout or within its ignored .roami directory"
        )
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    frozen = snapshot()
    private_json(args.output / "frozen.json", frozen)
    private_json(args.output / "contracts.json", cases)
    child_exit, cleanup_exit = None, None
    os.umask(0o077)
    try:
        with (args.output / "execution.log").open("w") as log:
            child = subprocess.run(
                [
                    str(launcher),
                    str(instance),
                    sys.executable,
                    str(Path(__file__).resolve()),
                    *sys.argv[1:],
                    "--isolated-child",
                ],
                cwd=REPOSITORY,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
            child_exit = child.returncode
    finally:
        with (args.output / "cleanup.log").open("w") as log:
            cleanup = subprocess.run(
                [str(launcher), str(instance), "--stop"],
                cwd=REPOSITORY,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
            cleanup_exit = cleanup.returncode
    try:
        evaluated = json.loads((args.output / "episodes.json").read_text())
    except (OSError, ValueError):
        evaluated = {
            "results": [],
            "failure": "EPISODE_RECEIPT_UNAVAILABLE",
            "usage_known": False,
        }
    results = evaluated["results"]
    expected = [(c["id"], s["id"]) for c in cases for s in c["scenarios"]]
    actual = [(r["case"], r["scenario"]) for r in results]
    unchanged = frozen == snapshot()
    selected_passed = (
        child_exit == cleanup_exit == 0
        and unchanged
        and actual == expected
        and all(r["passed"] for r in results)
    )
    receipt = {
        "mode": args.mode,
        "passed": selected_passed and all(c["complete_case"] for c in cases),
        "selected_passed": selected_passed,
        "complete_cases": all(c["complete_case"] for c in cases),
        "expected_scenarios": len(expected),
        "observed_scenarios": len(results),
        "passed_scenarios": sum(r["passed"] for r in results),
        "observed_user_turns": sum(len(r["checkpoints"]) for r in results),
        "verified_user_turns": sum(
            c["passed"] for r in results for c in r["checkpoints"]
        ),
        "expected_user_turns": sum(
            len(s["turns"]) for c in cases for s in c["scenarios"]
        ),
        **execution_summary(evaluated),
        "child_exit_code": child_exit,
        "cleanup_exit_code": cleanup_exit,
        "source_unchanged": unchanged,
        "frozen_sha256": hashlib.sha256(
            (args.output / "frozen.json").read_bytes()
        ).hexdigest(),
        "contracts_sha256": hashlib.sha256(
            (args.output / "contracts.json").read_bytes()
        ).hexdigest(),
        "saved_main_route_hash": evaluated.get("saved_main_route_hash"),
        "model_calls": sum(r["metrics"]["model_calls"] for r in results)
        if evaluated["usage_known"]
        else None,
        "external_model_calls": 0
        if args.mode == "fixture"
        else (
            sum(r["metrics"]["request_attempts"] for r in results)
            if evaluated["usage_known"]
            and all(r["metrics"]["request_attempts"] is not None for r in results)
            else None
        ),
        "observed_tokens": sum(r["metrics"]["observed_tokens"] for r in results),
        "usage_known": evaluated["usage_known"]
        and all(r["metrics"]["token_coverage"] == "complete" for r in results),
        "historical_suite_updated": False,
        "eligible_for_promotion": False,
        "background_execution": "synthetic_checkpoint",
    }
    private_json(args.output / "receipt.json", receipt)
    print(json.dumps(receipt))
    if not selected_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
