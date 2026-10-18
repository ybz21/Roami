"""Measure a configured Main provider through isolated durable conversation intake."""

import argparse
import asyncio
import json
import math
import os
import statistics
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from roami_agent.app import Runtime, configured_provider
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import Database, row, rows

CASES = [
    ("1加1等于几？只回答数字。", "2"),
    ("法国首都是哪里？只回答城市名。", "巴黎"),
    ("一周有几天？只回答数字。", "7"),
    ("水的化学式是什么？只回答化学式。", "H2O"),
    ("三角形有几条边？只回答数字。", "3"),
]


class NoMemoryModel:
    model = ""

    async def stream(self, messages, tools):
        yield ModelEvent("text", '{"memories":[]}')


async def measure(args):
    settings = replace(
        Settings.load(args.config),
        shell_roots=(),
        skill_roots=(),
        mcp_servers={},
        http_tools={},
        browser={},
        computer={},
        coding_directory=None,
        cli_bin="/nonexistent/benchmark-cli",
        timeout_seconds=args.timeout,
    )
    if not settings.model or not settings.endpoint:
        raise DomainError("MODEL_NOT_CONFIGURED")
    provider = configured_provider(settings, "main")
    samples = []
    with tempfile.TemporaryDirectory(prefix="roami-main-benchmark-") as directory:
        root = Path(directory)
        database = Database(root / "runtime.db", root, managed=False)
        await database.open()
        runtime = Runtime(
            database, provider, settings=settings, memory_model=NoMemoryModel()
        )

        async def reject_tool(args, binding):
            raise DomainError("BENCHMARK_TOOL_CALL")

        for tool in runtime.tools.registry.values():
            tool.handler = reject_tool
        try:
            await runtime.start()
            for number in range(args.samples):
                conversation = await runtime.conversations.create("benchmark")
                question, expected = CASES[number % len(CASES)]
                started = time.time_ns() // 1_000_000
                receipt = await runtime.chat.submit(
                    "benchmark", conversation["id"], str(number), question
                )
                async with asyncio.timeout(args.timeout + 5):
                    while True:
                        turn = await database.call(
                            lambda db, receipt=receipt: row(
                                db,
                                "SELECT state,finished_ms FROM turns WHERE id=?",
                                (receipt["turnId"],),
                            )
                        )
                        if turn["state"] in {"completed", "failed", "interrupted"}:
                            break
                        await asyncio.sleep(0.02)
                if turn["state"] != "completed":
                    raise DomainError("BENCHMARK_TURN_FAILED")
                first, usage, tools = await database.call(
                    lambda db, receipt=receipt: (
                        row(
                            db,
                            "SELECT created_ms FROM events WHERE turn_id=? AND kind='message.delta' ORDER BY id LIMIT 1",
                            (receipt["turnId"],),
                        ),
                        rows(
                            db,
                            "SELECT usage_json FROM prompt_manifests WHERE turn_id=?",
                            (receipt["turnId"],),
                        ),
                        db.execute(
                            "SELECT COUNT(*) FROM tool_calls WHERE turn_id=?",
                            (receipt["turnId"],),
                        ).fetchone()[0],
                    )
                )
                view = await runtime.conversations.messages(
                    "benchmark", conversation["id"]
                )
                answer = view["messages"][-1]["content"]["text"]
                correct = (
                    answer.replace("₂", "2").strip().strip("`*# .。!！\n").upper()
                    == expected
                )
                if not first or tools or not correct:
                    raise DomainError("BENCHMARK_DIRECT_ANSWER_INVALID")
                counters = []
                for item in usage:
                    value = json.loads(item["usage_json"]) if item["usage_json"] else {}
                    counters.append(
                        {
                            key: value.get(key)
                            for key in (
                                "inputTokens",
                                "outputTokens",
                                "cacheReadTokens",
                                "requestAttempts",
                            )
                        }
                    )
                samples.append(
                    {
                        "sample": number + 1,
                        "firstTextMs": first["created_ms"] - started,
                        "completedMs": turn["finished_ms"] - started,
                        "correct": correct,
                        "usage": counters,
                    }
                )
                print(json.dumps(samples[-1]), flush=True)
        finally:
            await runtime.close()
            await provider.close()
            await database.close()

    def distribution(field):
        values = sorted(sample[field] for sample in samples)
        return {
            "p50": statistics.median(values),
            "p95": values[math.ceil(0.95 * len(values)) - 1],
            "min": values[0],
            "max": values[-1],
        }

    report = {
        "measuredAt": datetime.now(UTC).isoformat(),
        "model": provider.model,
        "parameters": provider.parameters,
        "modelSettingsHash": provider.settings_hash,
        "n": len(samples),
        "method": "Sequential fresh conversations; original Main instructions/catalog; intake to persisted first text/completed turn. Memory extraction disabled and tool execution rejected. Excludes Go/browser/phone latency.",
        "firstTextMs": distribution("firstTextMs"),
        "completedMs": distribution("completedMs"),
        "samples": samples,
    }
    if args.output:
        descriptor = os.open(
            args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as target:
            json.dump(report, target, ensure_ascii=False, indent=2)
    print(
        json.dumps({key: value for key, value in report.items() if key != "samples"}),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.samples <= 100 or not 1 <= args.timeout <= 120:
        parser.error("samples must be 1..100 and timeout must be 1..120 seconds")
    if args.output and not args.output.parent.is_dir():
        parser.error("output directory must already exist")
    try:
        asyncio.run(measure(args))
    except DomainError as error:
        print(json.dumps({"error": error.code}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
