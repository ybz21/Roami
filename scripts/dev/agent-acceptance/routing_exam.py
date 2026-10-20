"""Exercise the configured real Main against isolated routing and admission fixtures.

Run from agent-runtime with uv run --frozen python
../scripts/dev/agent-acceptance/routing_exam.py --live --output /tmp/routing-exam.
No Worker or real coding session is started. Credentials are never exported.
"""

import argparse
import asyncio
import json
import re
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv

from roami_agent.app import Runtime, configured_provider
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.server.model_settings import load_model_settings
from roami_agent.storage.database import Database, rows


class QuietMemory:
    model = "acceptance-memory-disabled"

    async def stream(self, messages, tools):
        yield ModelEvent("text", '{"memories":[]}')


class MeasuredMain:
    def __init__(self, provider):
        self.provider, self.model = provider, provider.model
        self.provider_key, self.settings_hash = (
            provider.provider_key,
            provider.settings_hash,
        )
        self.calls = 0

    async def stream(self, messages, tools):
        self.calls += 1
        async for event in self.provider.stream(messages, tools):
            yield event


class ExamTargets:
    def __init__(self, installed):
        self.installed, self.sends = installed, []
        self.projects = [
            {
                "kind": "project",
                "projectId": "proj-roami",
                "label": "Roami",
                "archived": False,
                "defaultExecutor": "codex",
            },
            {
                "kind": "project",
                "projectId": "proj-swarm",
                "label": "Swarm",
                "archived": False,
                "defaultExecutor": "codex",
            },
        ]
        self.sessions = [
            {
                "kind": "session",
                "sessionId": "sid-settings",
                "label": "设置修复",
                "executor": "codex",
                "state": "live",
            },
            {
                "kind": "session",
                "sessionId": "sid-demo-1",
                "label": "演示",
                "executor": "codex",
                "state": "live",
                "projectId": "proj-roami",
            },
            {
                "kind": "session",
                "sessionId": "sid-demo-2",
                "label": "演示",
                "executor": "claude",
                "state": "live",
                "projectId": "proj-swarm",
            },
        ]

    async def executors(self, commands=None):
        return {
            "version": 1,
            "defaultExecutor": "codex",
            "candidates": [
                {
                    "kind": k,
                    "installed": k in self.installed,
                    "tracked": True,
                    "authentication": "unknown",
                    "usage": "unknown",
                }
                for k in ["codex", "claude"]
            ],
            "commandAvailability": {
                name: name in {"python3", "node", "git", "npm"}
                for name in commands or []
            },
        }

    async def search(self, kind, query="", *, offset=0, limit=10, project_id=None):
        values = self.projects if kind == "project" else self.sessions
        found = [
            v
            for v in values
            if (
                not query
                or query.casefold() in json.dumps(v, ensure_ascii=False).casefold()
            )
            and (not project_id or v.get("projectId") == project_id)
        ]
        return {
            "items": found[offset : offset + limit],
            "total": len(found),
            "nextOffset": None,
        }

    async def resolve(self, kind, identifier):
        values = self.projects if kind == "project" else self.sessions
        matches = [
            v
            for v in values
            if identifier
            in [
                v.get("projectId") if kind == "project" else v.get("sessionId"),
                v["label"],
            ]
        ]
        if len(matches) != 1:
            raise DomainError(
                "SESSION_TARGET_AMBIGUOUS"
                if len(matches) > 1
                else "SESSION_TARGET_NOT_FOUND"
            )
        return matches[0]

    async def send(self, sid, text, key, *, binding=None):
        await self.resolve("session", sid)
        self.sends.append({"sessionId": sid, "text": text, "key": key})
        return {"sessionId": sid, "state": "delivered", "executionTracked": False}

    async def overview(self):
        return {"projects": 2, "sessions": 3, "liveSessions": 3}


CASES = [
    (
        "Q01",
        "查一下济南今天的天气，只要温度和是否下雨，不写文件。",
        "简单公开查询只派 Native，使用 resourceOnly，不创建项目。",
        "weather",
    ),
    (
        "Q02",
        "在已有 Swarm 项目里制作一份无人机集群发展 PPT：独立调研多来源证据、比较国内外方案、设计图表，反复校验数据并根据结果调整内容，交付 pptx。你自主完成整个过程。",
        "复杂自主工作交专业执行器，绑定已发现的 Swarm 项目。",
        "complex",
    ),
    (
        "Q03",
        "用 Codex 修复已有 Roami 项目的设置保存问题，定位根因、修改代码、跑测试并提交 PR。",
        "遵守用户明确的 Codex 选择，绑定 Roami 项目。",
        "explicit",
    ),
    (
        "Q04",
        "把正文“验收完成”保存为 {directory}/summary.txt，然后读回核对，只做这一件事。",
        "有明确真实目录的有界文件任务交 Native，并保留目录。",
        "file",
    ),
    (
        "Q05",
        "当前节点是 Linux。请在 /Users/agent/work/roami-routing-exam-missing 下保存一份简短报告，这个目录是否存在我不清楚。",
        "不猜替代路径；目录不存在时不能接受任务，说明或询问真实目的地。",
        "missing",
    ),
    (
        "Q06",
        "把“继续修复并跑完测试”交给那个叫“演示”的现有会话。",
        "两个同名会话必须询问具体选择，不猜、不投递。",
        "ambiguous",
    ),
    (
        "Q07",
        "把“继续修复设置保存并跑完测试”发给现有的“设置修复”会话，不要新建任务或项目。",
        "准确向现有会话发送一次，不另建任务。",
        "session",
    ),
    (
        "Q08",
        "必须用 Claude Code 修复已有 Roami 项目的问题，定位原因并运行测试，不要换成别的执行器。",
        "Claude 未安装时明确阻塞或询问，不偷偷改派 Codex/Native。",
        "unavailable",
    ),
    (
        "Q09",
        "上次设置修复任务报 MODEL_HTTP_401。先告诉我原因和怎么恢复，别换个名字再建任务，也不要改我的密钥。",
        "说明模型鉴权问题，保留旧任务，不创建或启动重试。",
        "auth",
    ),
    (
        "Q10",
        "上次设置修复任务显示结果未知，我想继续。先核对现场，没确认旧执行已经停止之前不要重复运行。",
        "检查原任务；结果未知时禁止新任务和重跑。",
        "unknown",
    ),
    (
        "Q11",
        "继续刚才那个设置修复任务，保留它的执行器、工作区和已有修改，追加要求：补上保存失败的测试。不要另建任务。",
        "查询原任务并 task_steer，保持原 taskId/executor。",
        "continue",
    ),
    (
        "Q12",
        "两件独立的事：一是查济南今天会不会下雨，不保存文件；二是在已有 Roami 项目自主排查设置保存丢失，探索根因、改代码并反复跑测试。分别处理，互不取消。",
        "两个独立任务：天气 Native，只读；代码修复专业执行器，绑定 Roami。",
        "two",
    ),
    (
        "Q13",
        [
            "在已有 Roami 项目独立排查设置保存丢失，探索根因、修复并反复运行测试。",
            "另外查济南今天会不会下雨，只回答天气，不写文件。",
        ],
        "快速连问分别绑定各自消息，保留两个任务，不重复交办。",
        "rapid",
    ),
    ("Q14", "1 加 1 等于几？只回答数字。", "直接回答 2，不派任务。", "direct"),
    (
        "Q15",
        "查一下济南今天的天气，告诉我温度和降雨情况。",
        "未说明文件要求的简单查询默认只读 Native，不额外写文件或创建项目。",
        "weather",
    ),
    (
        "Q16",
        "在已有 Swarm 项目里自主研究无人机集群的国内外发展路线，多来源核对关键数据，比较不同技术方案，反复验证并调整结论，给出系统分析和最终建议。",
        "未说明文件要求的复杂任务交专业执行器，明确要求在 Swarm 工作区保存成果并返回文件链接。",
        "complex_default_file",
    ),
    (
        "Q17",
        "在已有 Swarm 项目里自主研究无人机集群的国内外发展路线，多来源核对关键数据，比较不同技术方案，反复验证并调整结论。只在聊天里给我系统分析和最终建议，禁止创建或修改任何文件。",
        "复杂任务仍交专业执行器，保留用户明确的禁止写文件要求。",
        "complex_chat_only",
    ),
    (
        "Q18",
        "用两句话解释什么是 Git worktree。",
        "未说明文件要求的简单问答直接回复，不建任务或写文件。",
        "direct_explanation",
    ),
    (
        "Q19",
        "工作目录是 {directory}。请自主调研无人机集群的技术路线，比较国内外不同方案，多来源交叉核对数据，反复验证并调整结论，给出完整分析和建议。",
        "未说明文件要求的复杂散任务使用准确目录，明确保存成果；不强制 Git 项目。",
        "complex_default_directory",
    ),
    (
        "Q20",
        "把这段话整理成三条要点：明天上午十点开项目评审会，请提前看需求稿，会上先确认范围再讨论风险，结论由负责人汇总后发给大家。",
        "未说明文件要求的简单整理直接在聊天回复，不建任务或额外写文件。",
        "direct_explanation",
    ),
]


async def run_case(provider, settings, output, number, case):
    ident, question, expected, kind = case
    root = output / f"round-{number}" / ident
    root.mkdir(parents=True, exist_ok=True)
    directory = root / "work"
    directory.mkdir(exist_ok=True)
    question = (
        [q.format(directory=directory) for q in question]
        if isinstance(question, list)
        else question.format(directory=directory)
    )
    targets = ExamTargets({"codex"} if kind == "unavailable" else {"codex", "claude"})
    database = Database(root / "runtime.db", root, managed=False)
    await database.open()
    counted = MeasuredMain(provider)
    with patch("roami_agent.app.TargetDirectory", lambda *args: targets):
        runtime = Runtime(
            database, counted, settings=settings, memory_model=QuietMemory()
        )

    async def block_external(args, binding):
        raise DomainError("WORKSPACE_REQUIRED")

    for name in ["bash"]:
        if name in runtime.tools.registry:
            runtime.tools.registry[name].handler = block_external
    started = time.monotonic()
    seeded = None
    try:
        conversation = await runtime.conversations.create("exam")
        cid = conversation["id"]
        if kind in {"auth", "unknown", "continue"}:
            seeded = await runtime.tasks.create(
                "exam",
                cid,
                "修复 Roami 设置保存问题，保留已有代码并补齐测试",
                key="seed",
                executor="codex",
                target={"kind": "project", "projectId": "proj-roami"},
                record_intent=True,
            )
            state = "interrupted" if kind == "unknown" else "failed"
            result = {
                "state": "failed",
                "summary": "MODEL_HTTP_401"
                if kind == "auth"
                else "EXECUTION_DEADLINE_OR_INTERRUPTION",
                "outcomeKnown": kind != "unknown",
            }

            def seed(db):
                db.execute("UPDATE tasks SET state=? WHERE id=?", (state, seeded["id"]))
                db.execute(
                    "UPDATE task_attempts SET state=?,result_json=?,finished_ms=1 WHERE task_id=?",
                    (
                        "unknown" if kind == "unknown" else "failed",
                        json.dumps(result),
                        seeded["id"],
                    ),
                )

            await database.call(seed, write=True)
        questions = question if isinstance(question, list) else [question]
        receipts = [
            await runtime.conversations.accept("exam", cid, f"user-{i}", text)
            for i, text in enumerate(questions)
        ]
        await runtime.start()
        async with asyncio.timeout(600):
            while True:
                current = await database.call(
                    lambda db: rows(
                        db, "SELECT state FROM turns WHERE trigger_kind='user'"
                    )
                )
                if current and all(
                    t["state"] in {"completed", "waiting_user", "failed", "interrupted"}
                    for t in current
                ):
                    break
                await asyncio.sleep(0.05)
        assert (
            await database.call(
                lambda db: db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE kind='task.run' AND state='running'"
                ).fetchone()[0]
            )
            == 0
        )
        continuation = None
        if kind in {"unknown", "continue"}:
            await runtime.tasks.revisions.advance()
            continuation = await runtime.tasks.get("exam", seeded["id"])
        tasks = await runtime.tasks.list("exam", cid)
        created = [t for t in tasks if not seeded or t["id"] != seeded["id"]]
        tools = await database.call(
            lambda db: rows(
                db,
                "SELECT x.tool_name,x.state,x.arguments_json,m.content_json AS result_json FROM tool_calls x LEFT JOIN messages m ON m.id=x.result_message_id ORDER BY x.rowid",
            )
        )
        view = await runtime.conversations.messages("exam", cid)
        answers = [
            m["content"].get("text", "")
            for m in view["messages"]
            if m["role"] == "assistant"
        ]
        turns = await database.call(
            lambda db: rows(
                db,
                "SELECT state FROM turns WHERE trigger_kind='user' ORDER BY created_ms",
            )
        )
        failures = await database.call(
            lambda db: rows(
                db,
                "SELECT payload_json FROM events WHERE kind='turn.failed' ORDER BY id",
            )
        )
        plans = [json.loads(t["intent_json"]) for t in created]
        operations = [t["tool_name"] for t in tools]
        questions_called = "ask_user" in operations
        if kind == "weather":
            passed = (
                len(plans) == 1
                and plans[0]["executor"] == "native"
                and plans[0]["target"].get("resourceOnly") is True
            )
        elif kind in {"complex", "explicit"}:
            passed = (
                len(plans) == 1
                and plans[0]["executor"] == "codex"
                and plans[0]["target"].get("projectId")
                == ("proj-swarm" if kind == "complex" else "proj-roami")
            )
        elif kind == "file":
            passed = (
                len(plans) == 1
                and plans[0]["executor"] == "native"
                and plans[0]["target"].get("directory") == str(directory)
                and not plans[0]["target"].get("resourceOnly")
            )
        elif kind in {
            "complex_default_file",
            "complex_default_directory",
            "complex_chat_only",
        }:
            plan = plans[0] if len(plans) == 1 else {}
            destination = plan.get("target", {})
            goal = plan.get("goal", "")
            passed = plan.get("executor") == "codex" and not destination.get(
                "resourceOnly"
            )
            if kind == "complex_default_directory":
                passed = (
                    passed
                    and destination.get("kind") == "new_session"
                    and destination.get("directory") == str(directory)
                )
            else:
                passed = passed and destination.get("projectId") == "proj-swarm"
            if kind == "complex_chat_only":
                passed = passed and bool(
                    re.search(
                        r"(不|禁止|严禁|不得).{0,15}(写|保存|创建|修改).{0,10}文件|只.{0,8}聊天",
                        goal,
                    )
                )
            else:
                passed = passed and bool(
                    re.search(
                        r"保存|写入|落盘|(?:输出|交付|生成|产出|持久).{0,30}(?:文件|\.md)|(?:目录|工作区|/[^\s]+).{0,40}(?:输出|产出|生成).{0,30}(?:报告|文档)|写.{0,15}报告|save|persist",
                        goal,
                        re.IGNORECASE,
                    )
                )
        elif kind == "direct_explanation":
            passed = (
                not plans
                and not targets.sends
                and bool("".join(answers).strip())
                and not {"file_write", "file_patch"}.intersection(operations)
            )
        elif kind == "missing":
            passed = (
                not plans
                and not targets.sends
                and (questions_called or "目录" in "".join(answers))
            )
        elif kind == "ambiguous":
            passed = not plans and not targets.sends and questions_called
        elif kind == "session":
            passed = (
                not plans
                and len(targets.sends) == 1
                and targets.sends[0]["sessionId"] == "sid-settings"
            )
        elif kind == "unavailable":
            passed = (
                not plans
                and not targets.sends
                and (questions_called or "Claude" in "".join(answers))
            )
        elif kind == "auth":
            passed = (
                not plans
                and not targets.sends
                and not any(
                    t["tool_name"] == "task_steer" and t["state"] == "succeeded"
                    for t in tools
                )
            )
        elif kind == "unknown":
            passed = (
                not plans
                and not targets.sends
                and continuation["task"]["revision"] == 1
                and continuation["task"]["latestAttempt"]["stopConfirmed"] is False
            )
        elif kind == "continue":
            steering = [
                json.loads(t["arguments_json"])
                for t in tools
                if t["tool_name"] == "task_steer" and t["state"] == "succeeded"
            ]
            passed = (
                not plans
                and len(steering) == 1
                and steering[0]["taskId"] == seeded["id"]
                and continuation["task"]["revision"] == 2
                and json.loads(continuation["task"]["intent_json"])["executor"]
                == "codex"
            )
        elif kind in {"two", "rapid"}:
            native = [
                p
                for p in plans
                if p["executor"] == "native" and p["target"].get("resourceOnly") is True
            ]
            coding = [
                p
                for p in plans
                if p["executor"] == "codex"
                and p["target"].get("projectId") == "proj-roami"
            ]
            passed = len(plans) == 2 and len(native) == 1 and len(coding) == 1
            if kind == "rapid":
                origins = {
                    plan["executor"]: task["origin_message_id"]
                    for task, plan in zip(created, plans)
                }
                passed = (
                    passed
                    and origins.get("codex") == receipts[0]["messageId"]
                    and origins.get("native") == receipts[1]["messageId"]
                )
        else:
            passed = not plans and "".join(answers).strip().strip("。.* \n") == "2"
        passed = passed and all(
            t["state"] in {"completed", "waiting_user"} for t in turns
        )
        result = {
            "id": ident,
            "round": number,
            "question": question,
            "expected": expected,
            "passed": passed,
            "seconds": round(time.monotonic() - started, 2),
            "modelCalls": counted.calls,
            "answers": answers,
            "newTasks": [
                {"id": t["id"], "originMessageId": t["origin_message_id"], **p}
                for t, p in zip(created, plans)
            ],
            "sessionDeliveries": targets.sends,
            "continuation": continuation,
            "tools": [
                {
                    **t,
                    "arguments_json": json.loads(t["arguments_json"]),
                    "result_json": json.loads(t["result_json"])
                    if t["result_json"]
                    else None,
                }
                for t in tools
            ],
            "turns": turns,
            "failureEvents": [json.loads(e["payload_json"]) for e in failures],
        }
    except Exception as exc:  # noqa: BLE001 — preserve the other samples after a failure
        error = exc.code if isinstance(exc, DomainError) else type(exc).__name__
        result = {
            "id": ident,
            "round": number,
            "question": question,
            "expected": expected,
            "passed": False,
            "seconds": round(time.monotonic() - started, 2),
            "error": error,
            "modelCalls": counted.calls,
        }
    finally:
        await runtime.close()
        await database.close()
    (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                k: result.get(k)
                for k in ["id", "round", "passed", "seconds", "modelCalls", "error"]
            }
        ),
        flush=True,
    )
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the configured provider; incurs model requests",
    )
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".roami/agent.toml"
    )
    parser.add_argument("--provider-root", type=Path, default=Path.home() / ".roami")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--cases", default="")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to run the configured real model")
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    args.output = args.output.expanduser().resolve()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    load_dotenv(args.provider_root / "agent-service.env", override=False)
    base = load_model_settings(Settings.load(args.config), args.provider_root)
    settings = replace(
        base,
        shell_roots=(),
        skill_roots=(),
        mcp_servers={},
        http_tools={},
        browser={},
        computer={},
        coding_directory=None,
        cli_bin="/nonexistent/routing-exam-cli",
        professional_executor="codex",
        workers=0,
        timeout_seconds=0,
        max_depth=0,
        context_window=base.context_window or 200000,
    )
    provider = configured_provider(settings, "main")
    selected = [c for c in CASES if not args.cases or c[0] in args.cases.split(",")]
    if not selected:
        parser.error("--cases did not select a known question")
    if any(
        (args.output / f"round-{n}" / case[0] / "runtime.db").exists()
        for n in range(1, args.rounds + 1)
        for case in selected
    ):
        parser.error("Use a fresh --output directory to preserve previous evidence")
    semaphore = asyncio.Semaphore(2)

    async def sample(number, case):
        async with semaphore:
            return await run_case(provider, settings, args.output, number, case)

    try:
        results = await asyncio.gather(
            *(sample(n, c) for n in range(1, args.rounds + 1) for c in selected)
        )
    finally:
        await provider.close()
    report = {
        "createdAt": datetime.now(UTC).isoformat(),
        "model": provider.model,
        "method": "真实配置 Main + 生产 Scheduler/mailbox/工具/路由/SQLite；仅在测试夹具将 Worker 槽位设0暂停执行副作用；项目和执行器目录为受控夹具；不启动真实 coding 会话；无生产数据写入。600秒仅为测试看门狗，不限制产品执行时长或工具次数。",
        "rounds": args.rounds,
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "results": results,
    }
    (args.output / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps({k: report[k] for k in ["model", "passed", "total"]}), flush=True)
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
