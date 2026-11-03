#!/usr/bin/env python3
"""Measure first-try tool use with the node's saved Main/Worker routes."""

import argparse
import asyncio
import json
from pathlib import Path

from roami_agent.app import Runtime
from roami_agent.improvement.entrypoints.node_models import node_model_settings
from roami_agent.improvement.integrations.tool_process import tool_process_metrics
from roami_agent.providers.factory import configured_provider
from roami_agent.storage.database import Database, row, rows

CASES = (
    ("main-shell", "main", "请用 shell 执行 printf 'ROAMI_BUILTIN_INPUT_OK'，只返回命令输出。"),
    ("main-status", "main", "查询当前对话还有没有后台任务在运行，用一句话回答。"),
    (
        "main-question",
        "main",
        "请询问我要把报告保存到哪个目录，给出“当前目录”和“指定目录”两个选项。",
    ),
    (
        "worker-files",
        "worker",
        "请用 write 写 note.txt，内容为 first\\nsecond\\nthird\\n（其中 \\n 表示换行），用 read 读取第二行，然后用 edit 把 second 替换成 changed，最后只回复完成。不要用 shell 代替这三个文件工具。",
    ),
)


async def run_case(settings, output, name, role, prompt):
    root = output / name
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    database = Database(root / "runtime.db", root / "runtime", managed=False)
    await database.open()
    main = configured_provider(settings, "main")
    worker = configured_provider(settings, "worker")
    runtime = Runtime(database, main, settings=settings, worker_model=worker)
    error = None
    try:
        conversation = await runtime.conversations.create("local")
        accepted = await runtime.conversations.accept("local", conversation["id"], name, prompt)
        job = await database.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (accepted["turnId"],))
        )
        turn = await runtime.mailbox.claim(job)
        if role == "worker":
            turn = dict(turn, workspace={"directory": str(workspace)})
        try:
            async with asyncio.timeout(240):
                await runtime.run_turn(turn, role)
        except Exception as exc:  # noqa: BLE001 — record acceptance failures, never provider text
            error = getattr(exc, "code", type(exc).__name__)
        calls = await database.call(
            lambda db: rows(
                db,
                "SELECT x.tool_name,x.state,x.arguments_json,native_content(m.content_json) AS result_json FROM tool_calls x LEFT JOIN messages m ON m.id=x.result_message_id WHERE x.turn_id=? ORDER BY x.rowid",
                (turn["id"],),
            )
        )
        current = await database.call(
            lambda db: row(db, "SELECT state FROM turns WHERE id=?", (turn["id"],))
        )
        records = []
        values = []
        for call in calls:
            message = json.loads(call["result_json"] or "{}")
            value = json.loads(message.get("text", "{}"))
            values.append(value)
            records.append(
                {
                    "tool": call["tool_name"],
                    "state": call["state"],
                    "fields": sorted(json.loads(call["arguments_json"])),
                    "error": value.get("error") if isinstance(value, dict) else None,
                }
            )
        process = tool_process_metrics(calls)
        passed = (
            error is None
            and current["state"] == "completed"
            and bool(records)
            and process["tool_errors"] == 0
        )
        if name == "main-shell":
            passed = passed and any(
                isinstance(v, dict) and v.get("stdout") == "ROAMI_BUILTIN_INPUT_OK" for v in values
            )
        elif name == "main-status":
            passed = passed and any(
                c["tool"] in {"task_status", "task_queue_reply"} for c in records
            )
        elif name == "main-question":
            passed = passed and any(
                isinstance(v, dict) and len(v.get("question", {}).get("options", [])) == 2
                for v in values
            )
        elif name == "worker-files":
            path = workspace / "note.txt"
            passed = (
                passed
                and path.is_file()
                and path.read_text() == "first\nchanged\nthird\n"
                and {"file_read", "file_write", "file_patch"} <= {c["tool"] for c in records}
            )
        result = {
            "case": name,
            "role": role,
            "model": settings.route(role).name,
            "state": current["state"],
            "passed": bool(passed),
            "first_attempt_succeeded": bool(records) and records[0]["state"] == "succeeded",
            "tool_failures": sum(c["state"] != "succeeded" for c in records),
            "error": error,
            "calls": records,
            "process": process,
        }
        (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result
    finally:
        await runtime.close()
        await main.close()
        await worker.close()
        await database.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-root", type=Path, default=Path.home() / ".roami")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    settings = await node_model_settings(args.config_root / "agent.toml", args.config_root)
    results = []
    for name, role, prompt in CASES:
        results.append(await run_case(settings, output, name, role, prompt))
    report = {
        "saved_routes_unchanged": True,
        "passed": all(r["passed"] for r in results),
        "cases": results,
    }
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
