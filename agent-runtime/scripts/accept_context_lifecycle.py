#!/usr/bin/env python3
"""Exercise a synthetic home handoff through the node's unchanged saved Main route."""

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from roami_agent.app import Runtime
from roami_agent.conversation.history_read import read_history
from roami_agent.improvement.entrypoints.node_models import node_model_settings
from roami_agent.protocol.identity import now_ms
from roami_agent.providers.factory import configured_provider
from roami_agent.storage.database import Database, row, rows
from roami_agent.storage.transcript_repository import message


async def run(args):
    settings = await node_model_settings(args.agent_config, args.data_root)
    route_hash = hashlib.sha256(
        json.dumps(asdict(settings.route("main")), sort_keys=True).encode()
    ).hexdigest()
    root = args.output
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (root / "runtime.db").exists():
        raise FileExistsError("Use a new acceptance output directory")
    database = Database(root / "runtime.db", root / "runtime", managed=False)
    await database.open()
    provider = configured_provider(settings, "main")
    runtime = Runtime(database, provider, settings=settings)
    try:
        c = await runtime.conversations.create("local")
        await database.call(
            lambda db: db.execute(
                "INSERT INTO main_conversations VALUES(?,?,?)",
                ("local", c["id"], now_ms()),
            ),
            write=True,
        )
        sources = [
            (
                "这一次的报告只列三条；这是单次格式要求，交付之后不要当成默认偏好。",
                "本次三条报告已交付；原始资料仍保留。",
            ),
            (
                "继续 Roami 发布准备。手机验收还没完成，暂时不要部署。",
                "发布准备仍未结束；尚未通过手机验收，也没有部署。",
            ),
            (
                "记下昨天的方案决定：原始记录永久保留，旧内容通过检索读取。",
                "已记录方案决定，来源为这条用户消息。",
            ),
        ]
        for index, (request, reply) in enumerate(sources):
            receipt = await runtime.conversations.accept(
                "local", c["id"], f"source-{index}", request
            )

            def finish(db, receipt=receipt, reply=reply):
                message(
                    db,
                    c["id"],
                    c["active_branch_id"],
                    "assistant",
                    {"text": reply + "\n执行过程记录。" * 1500},
                    turn_id=receipt["turnId"],
                )
                timestamp = now_ms() - 4 * 86_400_000
                db.execute(
                    "UPDATE turns SET state='completed',created_ms=?,finished_ms=? WHERE id=?",
                    (timestamp, timestamp, receipt["turnId"]),
                )
                db.execute(
                    "UPDATE messages SET created_ms=? WHERE turn_id=?",
                    (timestamp, receipt["turnId"]),
                )

            await database.call(finish, write=True)
        configuration = runtime.context.request_context()
        original = await runtime.context.project("local", c["id"], request_context=configuration)
        await runtime.context.maintenance.scan(force=True)
        jobs = await database.call(
            lambda db: rows(
                db,
                "SELECT * FROM jobs WHERE kind='context.maintain' AND state='queued'",
            )
        )
        for job in jobs:
            await runtime.context.maintenance.run(job["id"])
        brief = await database.call(
            lambda db: row(db, "SELECT * FROM context_briefs ORDER BY rowid DESC LIMIT 1")
        )
        states = await database.call(
            lambda db: rows(db, "SELECT state,payload_json FROM jobs WHERE kind='context.maintain'")
        )
        if not brief:
            result = {
                "passed": False,
                "route_hash": route_hash,
                "errors": [
                    json.loads(j["payload_json"]).get("error", "HANDOFF_NOT_READY") for j in states
                ],
            }
        else:
            receipt = await runtime.conversations.accept(
                "local", c["id"], "new-topic", "计算 17 加 25，只回答结果。"
            )
            plan = await runtime.context.project(
                "local",
                c["id"],
                through_turn=receipt["turnId"],
                request_context=configuration,
            )
            binding = {
                "owner": "local",
                "conversation": c["id"],
                "turnId": receipt["turnId"],
            }
            exact = await database.call(lambda db: read_history(db, binding, {"query": "只列三条"}))
            archive = await database.call(
                lambda db: row(db, "SELECT day_key FROM period_summaries LIMIT 1")
            )
            daily = await database.call(
                lambda db: read_history(db, binding, {"archiveDay": archive["day_key"]})
            )
            text = str(plan["messages"])
            checks = {
                "constraint_preserved": "不要部署" in text,
                "one_off_removed": "只列三条" not in text,
                "original_retrievable": bool(exact["messages"]),
                "daily_sources_available": bool(daily["parts"]),
                "prompt_smaller": plan["estimatedTokens"] < original["estimatedTokens"],
                "same_main": binding["conversation"] == c["id"],
                "saved_route_unchanged": route_hash
                == hashlib.sha256(
                    json.dumps(asdict(settings.route("main")), sort_keys=True).encode()
                ).hexdigest(),
            }
            result = {
                "passed": all(checks.values()),
                "checks": checks,
                "route_hash": route_hash,
                "before_estimated_tokens": original["estimatedTokens"],
                "after_estimated_tokens": plan["estimatedTokens"],
                "brief_items": json.loads(brief["items_json"]),
                "timezone": daily["parts"][0]["timezone"] if daily["parts"] else None,
            }
        path = root / "result.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return result["passed"]
    finally:
        await runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-config", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    raise SystemExit(0 if asyncio.run(run(parser.parse_args())) else 1)
