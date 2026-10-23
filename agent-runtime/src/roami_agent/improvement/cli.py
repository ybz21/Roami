"""Local CLI for frozen suites, daily experiments and inspectable RSI reports."""

import argparse
import asyncio
import json
import platform
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.contracts import (
    digest,
    implementation_hash,
    load_json,
    require,
    validate_suite,
)
from roami_agent.improvement.cycle import run_cycle, watch
from roami_agent.improvement.executors import ExternalExecutor, NativeFilesExecutor, private_json
from roami_agent.improvement.ledger import Ledger
from roami_agent.improvement.policy import BOUNDS, next_candidate
from roami_agent.improvement.protocol_suite import protocol_suite
from roami_agent.improvement.sampling import catalog_readiness, import_finqa
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


def resolve(base, value):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


async def execute(args):
    if args.command == "register-machine":
        from roami_agent.improvement.control import ImprovementControl

        return ImprovementControl(Ledger(args.ledger)).register_machine(
            args.owner, load_json(args.config, maximum=65536)
        )
    if args.command.startswith("research-"):
        from roami_agent.improvement.workflow import ResearchWorkflow

        workflow = ResearchWorkflow(Ledger(args.ledger))
        if args.command == "research-config":
            return workflow.configure(args.owner, load_json(args.config, maximum=65536))
        if args.command == "research-resume":
            return workflow.resume(args.owner, args.action)
        return workflow.snapshot(args.owner)
    if args.command == "smoke":
        root = args.output_root.resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        suite = protocol_suite()
        return await run_cycle(
            ledger=Ledger(root / "ledger.sqlite3"),
            owner="rsi-smoke",
            day=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            suite=suite,
            machine={
                "id": "local-protocol",
                "cache_mode": "cold",
                "environment_hash": digest(platform.uname()._asdict()),
            },
            executor=NativeFilesExecutor(Settings(), fixture=True),
            baseline={},
            candidate={"memory_recall_limit": 4},
            output_root=root / "runs",
            daily_tokens=512000,
            daily_episodes=4,
        )
    if args.command == "import-finance":
        suite = import_finqa(
            args.source,
            revision=args.revision,
            source_split=args.split,
            count=args.count,
            seed=args.seed,
            conversational=args.conversational,
        )
        private_json(args.output, suite)
        return {
            "suite": suite["id"],
            "cases": len(suite["cases"]),
            "hash": suite["content_hash"],
            "output": str(args.output),
            "official_leaderboard_comparable": False,
        }
    if args.command == "readiness":
        return catalog_readiness(
            load_json(args.bank),
            load_json(args.plan),
            [validate_suite(load_json(p)) for p in args.suite],
        )
    if args.command == "report":
        ledger = Ledger(args.ledger)
        return ledger.get(args.owner, args.cycle) if args.cycle else ledger.list(args.owner)
    if args.command == "recover":
        return {
            "interrupted": Ledger(args.ledger).recover(args.owner, stale_seconds=args.stale_seconds)
        }

    config = load_json(args.config, maximum=65536)
    base = args.config.resolve().parent
    require(config.get("schema_version") == 1)
    suite = validate_suite(load_json(resolve(base, config["suite"])))
    root = resolve(base, config["output_root"])
    require(not root.exists() or not root.is_symlink(), "RSI_PRIVATE_OUTPUT_REQUIRED")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(root.stat().st_mode & 0o077 == 0, "RSI_PRIVATE_OUTPUT_REQUIRED")
    ledger = Ledger(resolve(base, config["ledger"]))
    machine = config["machine"]
    require(isinstance(machine["id"], str) and bool(machine["id"]))
    mode = machine.get("mode")
    if mode in {"native_files", "protocol_fixture"}:
        settings = (
            Settings.load(resolve(base, config["model_config"]))
            if mode == "native_files"
            else Settings()
        )
        require(
            mode != "native_files" or bool(settings.endpoint and settings.model),
            "MODEL_NOT_CONFIGURED",
        )
        executor = NativeFilesExecutor(settings, fixture=mode == "protocol_fixture")
        machine = dict(
            machine,
            environment_hash=digest(
                {
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                    "release": platform.release(),
                    "operator_fingerprint": machine.get("environment_hash"),
                }
            ),
        )
    else:
        require(mode == "external", "RSI_MACHINE_MODE")
        executor = ExternalExecutor(machine["argv"], model_hash=machine["model_hash"])
    budgets = config["daily_budget"]
    baseline = (
        {key: getattr(settings, key) for key in BOUNDS}
        if mode in {"native_files", "protocol_fixture"}
        else {}
    )
    baseline.update(config.get("baseline", {}))

    async def run(day):
        if args.command == "watch":
            require(
                len(suite["cases"]) == 60
                and not any(c["layer"] == "smoke" for c in suite["cases"]),
                "RSI_FORMAL_SUITE_INCOMPLETE",
            )
        existing = [
            c
            for c in ledger.list(config["owner"], 100)
            if c["day"] == day and c["machine_id"] == machine["id"]
        ]
        if existing:
            return {
                "admitted": False,
                "cycle_id": existing[0]["id"],
                "reason": "machine_day_already_recorded",
            }
        candidate = {**baseline, **config.get("candidate", {})}
        if config.get("auto_candidates", False):
            require(
                all(c["split"] == "development" for c in suite["cases"]),
                "RSI_SEARCH_DEVELOPMENT_ONLY",
            )
            reports = [
                c["report"]
                for c in ledger.list(config["owner"], 100)
                if c["state"] == "completed"
                and c["report"].get("suite_hash") == suite["content_hash"]
                and c["report"].get("machine_hash") == digest(machine)
                and c["report"].get("model_hash") == executor.model_hash
                and c["report"].get("implementation_hash") == implementation_hash()
            ]
            candidate = next_candidate(baseline, reports) or baseline
        result = await run_cycle(
            ledger=ledger,
            owner=config["owner"],
            day=day,
            suite=suite,
            machine=machine,
            executor=executor,
            baseline=baseline,
            candidate=candidate,
            output_root=root,
            daily_tokens=budgets["tokens"],
            daily_episodes=budgets["episodes"],
            seed=config.get("seed", 20261023),
        )
        if args.command == "watch":
            print(json.dumps(result, ensure_ascii=False), flush=True)
        return result

    timezone = config.get("timezone", "Asia/Shanghai")
    if args.command == "watch":
        # Recover explicit stale leases once, never reissue their in-flight episodes.
        ledger.recover(config["owner"], stale_seconds=7200)
        await watch(run, timezone=timezone, hour=config.get("hour", 3))
        return None
    return await run(datetime.now(ZoneInfo(timezone)).date().isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("smoke")
    p.add_argument("--output-root", required=True, type=Path)
    for name in ("cycle", "watch"):
        p = commands.add_parser(name)
        p.add_argument("--config", required=True, type=Path)
    p = commands.add_parser("import-finance")
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--revision", required=True)
    p.add_argument("--split", required=True, choices=("train", "dev", "test"))
    p.add_argument("--conversational", action="store_true")
    p.add_argument("--count", type=int, default=3)
    p.add_argument("--seed", type=int, default=20261023)
    p.add_argument("--output", required=True, type=Path)
    p = commands.add_parser("readiness")
    p.add_argument("--bank", required=True, type=Path)
    p.add_argument("--plan", required=True, type=Path)
    p.add_argument("--suite", action="append", default=[], type=Path)
    for name in ("report", "recover"):
        p = commands.add_parser(name)
        p.add_argument("--ledger", required=True, type=Path)
        p.add_argument("--owner", required=True)
        if name == "report":
            p.add_argument("--cycle")
        else:
            p.add_argument("--stale-seconds", type=int, default=7200)
    for name in ("research-config", "research-status", "research-resume", "register-machine"):
        p = commands.add_parser(name)
        p.add_argument("--ledger", required=True, type=Path)
        p.add_argument("--owner", required=True)
        if name in {"research-config", "register-machine"}:
            p.add_argument("--config", required=True, type=Path)
        if name == "research-resume":
            p.add_argument("--action", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(execute(args))
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (DomainError, OSError, KeyError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {"error": error.code if isinstance(error, DomainError) else "RSI_INVALID_INPUT"}
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
