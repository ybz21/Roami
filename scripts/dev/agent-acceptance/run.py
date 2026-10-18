#!/usr/bin/env python3
"""Run the documented dialogue matrix against an explicitly isolated Roami instance."""

import argparse
import concurrent.futures
import html
import http.cookiejar
import http.server
import json
import shlex
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REPORT = REPO / "docs/design/20261017-agent框架设计/reviews/20261019-e2e-cases"


def render():
    matrix = json.loads((REPORT / "cases.json").read_text())
    results_path = REPORT / "results.json"
    results = (
        json.loads(results_path.read_text()) if results_path.exists() else {"runs": []}
    )
    latest = {r["id"]: r for r in results["runs"]}
    rows = []
    for case in matrix["cases"]:
        result = latest.get(case["id"], {})
        detail = result.get("reason", "") or result.get(
            "answer", result.get("postCompactAnswer", "")
        )
        rows.append(
            "<tr>"
            + "".join(
                "<td>" + html.escape(str(value)) + "</td>"
                for value in (
                    case["id"],
                    case["category"],
                    case["prompt"],
                    case["expected"]
                    + (
                        " 前置：" + case["precondition"]
                        if case.get("precondition")
                        else ""
                    ),
                    result.get("status", "待测"),
                    result.get("seconds", ""),
                    detail,
                )
            )
            + "</tr>"
        )
    passed = sum(r.get("status") == "通过" for r in latest.values())
    page = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Roami 对话验收 · 20261019</title><link rel="stylesheet" href="../../technical/tech.css"></head><body><div class="shell"><header class="top"><span class="brand">Roami / Dialogue Acceptance</span><nav class="topnav"><a href="../../technical/index.html">技术设计</a><a href="cases.json">用例数据</a><a href="results.json">完整结果</a></nav></header><main class="scroll"><div class="wrap"><header class="tt-pagehead"><div class="eyebrow">2026-10-19 · REAL MODEL EVALUATION</div><h1>问答与派活验收</h1><p>参考 GAIA 能力维度自编题，覆盖问答、网页、附件、派活、记忆、命令和错误恢复；不是官方 GAIA 成绩。</p></header><section><h2>执行口径</h2><p>隔离数据库、独立 tmux socket、测试项目。使用当前真实主模型和后台模型、真实 Roami CLI 与浏览器。已有会话是专用终端接收器，只验证可靠投递；新建 Codex / Claude 任务使用真实专业智能体。没有触碰用户生产会话。每轮保留结果，不覆盖失败历史。</p><p>答案匹配是自动初筛；来源、派活回执、错误和耗时另查。单个用例通过不代表整体体验达标。压缩入队与压缩成功分开；模型调用失败不算通过。依据：<a href="https://arxiv.org/abs/2311.12983">GAIA 官方论文</a>、<a href="https://huggingface.co/datasets/gaia-benchmark/GAIA">官方数据集</a>。</p><p>RESULT_COUNT</p></section><section><h2>逐项预期与实际结果</h2><div class="tablewrap"><table><thead><tr><th>编号</th><th>类别</th><th>用户问题</th><th>预期与验收</th><th>最新状态</th><th>秒</th><th>实际结果 / 失败原因</th></tr></thead><tbody>ROWS</tbody></table></div></section></div></main></div></body></html>"""
    findings = "".join(
        "<li><b>"
        + html.escape(item["status"] + "：" + item["title"])
        + "</b><p>"
        + html.escape(item["detail"])
        + "</p></li>"
        for item in results.get("findings", [])
    )
    replay = """<section><h2>问题、修复与验收边界</h2><ul>FINDINGS</ul></section><section><h2>复跑方式</h2><p>先构建本仓库CLI并准备可连接的测试Chrome CDP。配置来自节点私有配置文件，不把Key写进用例或版本库。使用Python环境：uv run --project agent-runtime python。</p><pre>python scripts/dev/agent-acceptance/instance.py --state /tmp/agent-acceptance-state.json --cli backend/dist/roami-linux-amd64 --cdp http://127.0.0.1:9222
python scripts/dev/agent-acceptance/run.py --state /tmp/agent-acceptance-state.json
python scripts/dev/agent-acceptance/run.py --state /tmp/agent-acceptance-state.json --only G12,D03,C03
python scripts/dev/agent-acceptance/instance.py --state /tmp/agent-acceptance-state.json --stop</pre><p>只停止该私有实例的进程组和独立tmux socket，保留数据库、日志和报告用于溯源。只选M02复跑时，先确保M01已经在该实例执行。</p></section>""".replace(
        "FINDINGS", findings
    )
    page = page.replace(
        "<section><h2>逐项预期与实际结果</h2>",
        replay + "<section><h2>逐项预期与实际结果</h2>",
    )
    (REPORT / "index.html").write_text(
        page.replace(
            "RESULT_COUNT",
            f"共 {len(matrix['cases'])} 项，已测 {len(latest)} 项，最新通过 {passed} 项。",
        ).replace("<tbody>ROWS</tbody>", "<tbody>" + "".join(rows) + "</tbody>")
    )


class Instance:
    def __init__(self, path):
        self.state = json.loads(Path(path).read_text())
        self.root = Path(self.state["root"]).resolve()
        if not str(self.root).startswith(
            "/tmp/roami-acceptance-20261019-"
        ) or not self.state["namespace"].startswith("roami-acceptance-20261019-"):
            raise ValueError("An isolated acceptance instance is required")
        self.env = dict(
            x.split("=", 1)
            for x in Path(f"/proc/{self.state['agentPid']}/environ")
            .read_text()
            .split("\0")
            if "=" in x
        )
        if self.env.get("ROAMI_HOME") != str(self.root):
            raise ValueError("Instance environment does not match the isolated root")
        self.binary = "/tmp/roami-dispatch-e2e-bin"
        self.lock = threading.Lock()
        self.memory_cid = None

    def request(self, path, data=None, raw=None):
        jar = http.cookiejar.CookieJar()
        for c in json.loads((self.root / "browser-cookies.json").read_text()):
            jar.set_cookie(
                http.cookiejar.Cookie(
                    0,
                    c["name"],
                    c["value"],
                    None,
                    False,
                    c["domain"],
                    False,
                    False,
                    c["path"],
                    True,
                    False,
                    None,
                    True,
                    None,
                    None,
                    {},
                    False,
                )
            )
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        body = (
            raw
            if raw is not None
            else json.dumps(data).encode()
            if data is not None
            else None
        )
        request = urllib.request.Request(
            self.state["base"] + path,
            data=body,
            headers={
                "Content-Type": "application/octet-stream"
                if raw is not None
                else "application/json"
            },
        )
        with opener.open(request, timeout=25) as response:
            return json.load(response)["data"]

    def db(self, sql, args=()):
        connection = sqlite3.connect(
            "file:" + str(self.root / "database/agents/runtime.db") + "?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute(sql, args)]
        finally:
            connection.close()

    def fixtures(self):
        receiver = self.root / "receiver.py"
        receiver.write_text(
            'import sys,json\nfrom pathlib import Path\np=Path(sys.argv[1])\nfor line in sys.stdin:\n with p.open("a") as f: f.write(json.dumps(line.strip())+"\\n")\n'
        )
        labels = [
            "验收一号",
            "验收二号",
            "验收三号",
            "验收四号",
            "重复验收",
            "重复验收",
        ]
        for index, label in enumerate(labels):
            name = f"acceptance-receiver-{index}"
            output = self.root / f"received-{index}.jsonl"
            if output.exists():
                continue
            exists = subprocess.run(
                [str(self.root / "tmux"), "has-session", "-t", "=" + name],
                env=self.env,
                capture_output=True,
                check=False,
            )
            if exists.returncode == 0:
                continue
            subprocess.run(
                [
                    str(self.root / "tmux"),
                    "new-session",
                    "-d",
                    "-s",
                    name,
                    "-c",
                    self.state["projectDir"],
                    shlex.join(["python3", str(receiver), str(output)]),
                ],
                env=self.env,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    str(self.root / "tmux"),
                    "set-option",
                    "-t",
                    "=" + name + ":",
                    "@roam_name",
                    label,
                ],
                env=self.env,
                check=True,
                capture_output=True,
            )
        for name in ["codex-loose", "claude-loose"]:
            (self.root / "workspaces" / name).mkdir(exist_ok=True)
        pages = self.root / "web-fixture"
        pages.mkdir(exist_ok=True)
        (pages / "index.html").write_text(
            '<!doctype html><meta charset="utf-8"><h1>验收观测站</h1><p>旧会议安排：2026-10-20，A馆。</p><a href="data.html">观测数据</a><a href="correction.html">更正公告</a>'
        )
        (pages / "data.html").write_text(
            '<!doctype html><meta charset="utf-8"><h1>观测数据</h1><p>北站降水12毫米，南站降水24毫米。统计口径：两站算术平均。</p>'
        )
        (pages / "correction.html").write_text(
            '<!doctype html><meta charset="utf-8"><h1>更正公告</h1><p>最终会议日期为2026-10-22，地点B馆。此前安排作废。</p>'
        )
        handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(
            *args, directory=str(pages), **kwargs
        )
        self.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.web.serve_forever, daemon=True).start()
        self.fixture_url = "http://127.0.0.1:" + str(self.web.server_port)

    def run(self, case):
        start = time.monotonic()
        result = {
            "id": case["id"],
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "status": "未通过",
        }
        try:
            cid = self.request(
                "/api/agent/conversations",
                {
                    "title": "隔离验收 " + case["id"],
                    "requestKey": case["id"] + "-" + str(time.time_ns()),
                },
            )["id"]
            result["conversationId"] = cid
            prompt = (
                case["prompt"]
                .replace("{workspace}", str(self.root / "workspaces"))
                .replace("{fixture}", self.fixture_url)
            )
            delivery_marker = case["check"].get("delivery", "")
            prior_deliveries = (
                sum(
                    delivery_marker in line
                    for file in self.root.glob("received-*.jsonl")
                    for line in file.read_text().splitlines()
                )
                if delivery_marker
                else 0
            )
            payload = {
                "text": prompt,
                "requestKey": case["id"] + "-message-" + str(time.time_ns()),
            }
            if attachment := case.get("attachment"):
                if attachment.get("image"):
                    import io

                    from PIL import Image, ImageDraw, ImageFont

                    picture = Image.new("RGB", (1200, 300), "white")
                    ImageDraw.Draw(picture).text(
                        (60, 80),
                        "ROAMI 7284",
                        fill="black",
                        font=ImageFont.truetype(
                            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 130
                        ),
                    )
                    body = io.BytesIO()
                    picture.save(body, "PNG")
                    raw = body.getvalue()
                else:
                    raw = attachment["text"].encode()
                query = urllib.parse.urlencode(
                    {"filename": attachment["name"], "requestKey": str(time.time_ns())}
                )
                uploaded = self.request("/api/agent/attachments?" + query, raw=raw)
                payload["attachmentIds"] = [uploaded["id"]]
            if case["id"] == "C03":
                self.request(
                    "/api/agent/conversations/" + cid + "/messages",
                    {
                        "text": "以下是历史测试记录，请只回复：压缩前验收标记 spruce-9042。\n"
                        + "\n".join(
                            f"第{i}条记录：今天检查了项目索引、会话归属、任务回报、消息状态和页面导航，结果已保留以便追溯。"
                            for i in range(100)
                        ),
                        "requestKey": "compact-seed-" + cid,
                    },
                )
                until = time.monotonic() + 90
                while time.monotonic() < until:
                    seeded = self.request(
                        "/api/agent/conversations/" + cid + "/messages"
                    )
                    if seeded["turns"] and all(
                        t["state"] == "completed" for t in seeded["turns"]
                    ):
                        break
                    time.sleep(0.4)
                else:
                    raise AssertionError("Pre-compaction dialogue did not complete")
            receipt = self.request(
                "/api/agent/conversations/" + cid + "/messages", payload
            )
            result["receipt"] = receipt
            check = case["check"]
            if "receipt" in check:
                assert receipt["kind"] == check["receipt"], receipt
                for text in check.get("containsReceipt", []):
                    assert text in json.dumps(receipt), "Receipt missing " + text
                if check["receipt"] == "compaction":
                    deadline = time.monotonic() + 150
                    while time.monotonic() < deadline:
                        jobs = self.db(
                            "SELECT * FROM jobs WHERE id=?", (receipt["operationId"],)
                        )
                        if jobs and jobs[0]["state"] not in ["queued", "running"]:
                            result["compactionState"] = json.loads(
                                jobs[0]["payload_json"]
                            ).get("state")
                            assert result["compactionState"] == "completed", result[
                                "compactionState"
                            ]
                            assert jobs[0]["state"] in [
                                "completed",
                                "succeeded",
                                "done",
                            ], jobs[0]["state"]
                            break
                        time.sleep(0.5)
                    else:
                        raise AssertionError("Compaction did not finish")
                    snapshots = self.db(
                        "SELECT s.id FROM context_snapshots s JOIN branches b ON b.id=s.branch_id WHERE b.conversation_id=? AND s.state='ready'",
                        (cid,),
                    )
                    assert snapshots, "No actual compacted context snapshot"
                    self.request(
                        "/api/agent/conversations/" + cid + "/messages",
                        {
                            "text": "刚才的验收标记是什么？请只给标记。",
                            "requestKey": "after-compact-" + cid,
                        },
                    )
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        continued = self.request(
                            "/api/agent/conversations/" + cid + "/messages"
                        )
                        if len(continued["turns"]) >= 2 and all(
                            t["state"] == "completed" for t in continued["turns"]
                        ):
                            result["postCompactAnswer"] = [
                                m["content"].get("text", "")
                                for m in continued["messages"]
                                if m["role"] == "assistant"
                            ][-1]
                            assert "spruce-9042" in result["postCompactAnswer"], (
                                "Compaction lost the required marker"
                            )
                            break
                        time.sleep(0.4)
                    else:
                        raise AssertionError("Post-compaction chat did not complete")
                result["status"] = "通过"
                return result
            deadline = time.monotonic() + 240
            first_partial = None
            while time.monotonic() < deadline:
                snapshot = self.request("/api/agent/conversations/" + cid + "/messages")
                tasks = self.request("/api/agent/tasks?conversationId=" + cid)
                turns = snapshot["turns"]
                active = any(t["state"] in ["queued", "running"] for t in turns)
                task_active = any(
                    t["state"] in ["queued", "preparing", "running", "verifying"]
                    for t in tasks
                )
                assistant = [
                    m["content"].get("text", "")
                    for m in snapshot["messages"]
                    if m["role"] == "assistant"
                ]
                if first_partial is None and any(assistant):
                    first_partial = round(time.monotonic() - start, 2)
                    result["textObservedWhileRunning"] = active
                if turns and not active and not task_active:
                    break
                time.sleep(0.4)
            else:
                raise AssertionError("Dialogue exceeded 240 seconds")
            answer = "\n".join(assistant)
            calls = self.db(
                "SELECT tc.tool_name,tc.state,tc.arguments_json FROM tool_calls tc JOIN turns t ON t.id=tc.turn_id WHERE t.conversation_id=? ORDER BY tc.created_ms",
                (cid,),
            )
            names = [c["tool_name"] for c in calls]
            result.update(
                answer=answer,
                firstTextSeconds=first_partial,
                turns=[t["state"] for t in turns],
                tools=[{"name": c["tool_name"], "state": c["state"]} for c in calls],
                tasks=[
                    {"state": t["state"], "intent": json.loads(t["intent_json"])}
                    for t in tasks
                ],
            )
            assert all(t["state"] in ["completed", "waiting_user"] for t in turns), (
                "Turn failed: " + str(result["turns"])
            )
            for text in check.get("contains", []):
                assert text.lower() in answer.lower(), "Answer missing " + text
            if "any" in check:
                assert any(text in answer for text in check["any"]), (
                    "No truthful expected response"
                )
            if check.get("noTools"):
                assert not calls, "Unnecessary tools: " + str(names)
            if check.get("noTasks"):
                assert not tasks, "Unexpected background task"
            for name in check.get("tools", []):
                assert name in names, "Missing operation " + name
            if check.get("anyTools"):
                lookup = any(name in names for name in check["anyTools"])
                if not lookup and case["id"] == "D06":
                    failures = self.db(
                        "SELECT m.content_json FROM tool_calls tc JOIN turns t ON t.id=tc.turn_id "
                        "JOIN messages m ON m.id=tc.result_message_id WHERE t.conversation_id=? "
                        "AND tc.tool_name='session_send' AND tc.state='failed'",
                        (cid,),
                    )
                    lookup = any(
                        "SESSION_TARGET_NOT_FOUND" in item["content_json"]
                        for item in failures
                    )
                assert lookup, "No target lookup or validated not-found receipt"
            if check.get("noQuestions"):
                assert "ask_user" not in names, "Repeated permission question"
            if check.get("question"):
                questions = [
                    json.loads(c["arguments_json"])
                    for c in calls
                    if c["tool_name"] == "ask_user"
                ]
                assert questions and 2 <= len(questions[-1]["options"]) <= 4, (
                    "No multiple-choice question"
                )
            delivered = [
                c
                for c in calls
                if c["tool_name"] == "session_send"
                and c["state"] in ["succeeded", "delivered"]
            ]
            if check.get("noDelivery"):
                assert not delivered, "Unwanted message delivery"
            if marker := check.get("delivery"):
                assert len(delivered) == 1, "Expected exactly one real delivery"
                received = [
                    line
                    for f in self.root.glob("received-*.jsonl")
                    for line in f.read_text().splitlines()
                    if marker in line
                ]
                assert len(received) == prior_deliveries + 1, (
                    "Receiver did not get exactly one new message"
                )
            if check.get("taskSuccess"):
                assert tasks and all(t["state"] == "succeeded" for t in tasks), (
                    "Background task did not succeed"
                )
            if check.get("browser"):
                browser_calls = self.db(
                    "SELECT tc.tool_name,tc.state FROM tool_calls tc JOIN turns tr ON tr.id=tc.turn_id JOIN branches b ON b.id=tr.branch_id JOIN task_attempts a ON a.native_branch_id=b.id JOIN tasks t ON t.id=a.task_id WHERE t.origin_conversation_id=? AND tc.tool_name LIKE 'browser_%'",
                    (cid,),
                )
                result["browserCalls"] = browser_calls
                assert any(c["state"] == "succeeded" for c in browser_calls), (
                    "No real browser evidence"
                )
                assert "http" in answer, "Missing source URL"
            if check.get("executor"):
                assert len(tasks) == 1, "Expected exactly one professional task"
                intent = json.loads(tasks[0]["intent_json"])
                assert (
                    intent["executor"] == check["executor"]
                    and intent["target"]["kind"] == check["target"]
                ), "Wrong delegation target"
                attempts = self.db(
                    "SELECT state,result_json FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC",
                    (tasks[0]["id"],),
                )
                result["executorStates"] = [a["state"] for a in attempts]
                assert any(
                    check["taskMarker"] in (a["result_json"] or "") for a in attempts
                ), "No durable executor result marker"
                assert check["taskMarker"] in answer, (
                    "Main did not report executor result"
                )
            if marker := check.get("memory"):
                memories = self.db(
                    "SELECT * FROM memory_records WHERE owner_id='local' AND state='active'"
                )
                assert any(marker in json.dumps(m) for m in memories), (
                    "No active durable memory"
                )
                result["storedMemoryVerified"] = True
            if check.get("discovery"):
                assert "tool_search" in names or "skill_read" in names, (
                    "No actual capability discovery"
                )
            result["status"] = "通过"
        except (
            AssertionError,
            OSError,
            ValueError,
            KeyError,
            sqlite3.Error,
            TimeoutError,
        ) as exc:
            result["reason"] = str(exc)[:1200]
        finally:
            result["seconds"] = round(time.monotonic() - start, 2)
            with self.lock:
                path = REPORT / "results.json"
                saved = json.loads(path.read_text()) if path.exists() else {"runs": []}
                saved["runs"].append(result)
                path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n")
                render()
                print(
                    json.dumps(
                        {
                            k: result.get(k)
                            for k in ["id", "status", "seconds", "reason"]
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state")
    parser.add_argument("--only", default="")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    if args.render:
        render()
        return
    instance = Instance(args.state)
    instance.fixtures()
    cases = json.loads((REPORT / "cases.json").read_text())["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    try:
        independent = [c for c in cases if c["id"] not in ["M01", "M02"]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(instance.run, independent))
        for case in cases:
            if case["id"] in ["M01", "M02"]:
                instance.run(case)
    finally:
        instance.web.shutdown()


if __name__ == "__main__":
    main()
