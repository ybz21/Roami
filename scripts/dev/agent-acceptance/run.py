#!/usr/bin/env python3
"""Run the documented dialogue matrix against an explicitly isolated Roami instance."""

import argparse
import concurrent.futures
import fcntl
import html
import http.cookiejar
import http.server
import json
import secrets
import shlex
import sqlite3
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from document_chains import (
    execution_trace,
    seed_document_sources,
    validate_document_chain,
    validate_link_navigation,
    validate_memory_recall,
    validate_memory_write,
)

REPO = Path(__file__).resolve().parents[3]
REPORT = REPO / "docs/design/20261017-agent框架设计/reviews/20261019-e2e-cases"


def render():
    matrix = json.loads((REPORT / "cases.json").read_text())
    results_path = REPORT / "results.json"
    results = (
        json.loads(results_path.read_text()) if results_path.exists() else {"runs": []}
    )
    latest = {r["id"]: r for r in results["runs"]}
    rows, baseline_rows = [], []
    for case in matrix["cases"]:
        result = latest.get(case["id"], {})
        evidence = {
            key: result[key]
            for key in (
                "agentMechanismProof",
                "toolTimeline",
                "handoffProof",
                "professionalReadbackProof",
                "navigationProof",
                "attachmentTransferProof",
                "memoryWriteProof",
                "memoryRecallProof",
                "userPreferenceScopeProof",
                "documentProof",
            )
            if key in result
        }
        proof = (
            "<details><summary>查看执行证据</summary><pre>"
            + html.escape(json.dumps(evidence, ensure_ascii=False, indent=2))
            + "</pre></details>"
            if evidence
            else ""
        )
        artifact = result.get("documentProof", {}).get("fileUrl")
        delivery = (
            '<p><a href="'
            + html.escape(artifact, quote=True)
            + '">打开实际产物</a></p>'
            if artifact
            else ""
        )
        reply = result.get("answer", result.get("postCompactAnswer", ""))
        detail_html = html.escape(result.get("reason", ""))
        if reply:
            detail_html += (
                "<details><summary>查看实际回复</summary><pre>"
                + html.escape(reply)
                + "</pre></details>"
            )
        target_rows = baseline_rows if case.get("baselineOnly") else rows
        target_rows.append(
            "<tr>"
            + "".join(
                "<td>"
                + (
                    "<details><summary>用户问题</summary><p>"
                    + html.escape(str(value))
                    + "</p></details>"
                    if index == 2
                    else html.escape(str(value))
                )
                + "</td>"
                for index, value in enumerate(
                    (
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
                    )
                )
            )
            + "<td>"
            + detail_html
            + delivery
            + proof
            + "</td></tr>"
        )
    agent_ids = {case["id"] for case in matrix["cases"] if not case.get("baselineOnly")}
    agent_tested = {key: value for key, value in latest.items() if key in agent_ids}
    agent_passed = sum(value.get("status") == "通过" for value in agent_tested.values())
    executions = {
        (item["id"], item.get("conversationId", item.get("started")))
        for item in results["runs"]
        if not item.get("auditOnly") or item.get("recoveredFromDatabase")
    }
    rechecks = sum(bool(item.get("auditOnly")) for item in results["runs"])
    page = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Roami 对话验收 · 20261019</title><link rel="stylesheet" href="../../technical/tech.css"></head><body><div class="shell"><header class="top"><span class="brand">Roami / Agent Acceptance</span><nav class="topnav"><a href="../../technical/index.html">技术设计</a><a href="cases.json">用例数据</a><a href="results.json">完整结果</a></nav></header><main class="scroll"><div class="wrap"><header class="tt-pagehead"><div class="eyebrow">2026-10-19 · AGENT WORKFLOW EVALUATION</div><h1>智能体执行链验收</h1><p>主验收关注工具执行、按需组合Skill、自动记忆和跨任务产物交付；常识问答仅作模型基线，不计入智能体通过率。</p></header><section><h2>执行口径</h2><p>隔离数据库、独立 tmux socket、测试项目。使用当前真实主模型和后台模型、真实 Roami CLI 与浏览器。已有会话是专用终端接收器，只验证可靠投递；新建 Codex / Claude 任务使用真实专业智能体。没有触碰用户生产会话。每轮保留结果，不覆盖失败历史。</p><p>主验收以工具回执、Skill版本和凭证、消息来源、记忆写入与召回清单、产物读回及实际下载为证据，答案文字匹配只作辅助。单个用例通过不代表整体体验达标。压缩入队与压缩成功分开；模型调用失败不算通过。依据：<a href="https://arxiv.org/abs/2311.12983">GAIA 官方论文</a>、<a href="https://huggingface.co/datasets/gaia-benchmark/GAIA">官方数据集</a>。</p><p>RESULT_COUNT</p></section><section><h2>逐项预期与实际结果</h2><div class="tablewrap"><table><thead><tr><th>编号</th><th>类别</th><th>用户问题</th><th>预期与验收</th><th>最新状态</th><th>秒</th><th>实际结果 / 失败原因</th></tr></thead><tbody>ROWS</tbody></table></div></section></div></main></div></body></html>"""
    findings = "".join(
        "<li><b>"
        + html.escape(item["status"] + "：" + item["title"])
        + "</b><p>"
        + html.escape(item["detail"])
        + "</p></li>"
        for item in results.get("findings", [])
    )
    replay = """<section><h2>问题、修复与验收边界</h2><details><summary>展开问题与边界</summary><ul>FINDINGS</ul></details></section><section><h2>复跑方式</h2><details><summary>展开复跑命令</summary><p>先构建本仓库CLI并准备可连接的测试Chrome CDP。配置来自节点私有配置文件，不把Key写进用例或版本库。使用Python环境：uv run --project agent-runtime python。</p><pre>python scripts/dev/agent-acceptance/instance.py --state /tmp/agent-acceptance-state.json --cli backend/dist/roami-linux-amd64 --cdp http://127.0.0.1:9222 --document-skills
python scripts/dev/agent-acceptance/run.py --state /tmp/agent-acceptance-state.json
python scripts/dev/agent-acceptance/run.py --state /tmp/agent-acceptance-state.json --only G12,D03,C03
python scripts/dev/agent-acceptance/instance.py --state /tmp/agent-acceptance-state.json --stop</pre><p>只停止该私有实例的进程组和独立tmux socket，保留数据库、日志和报告用于溯源。文档链路的两个外部Skill为隔离测试夹具，不安装到生产。每个实例生成独立凭证，用于证明实际读取及跨流程传递。只选M02复跑时，先确保M01已经在该实例执行；R08依赖同实例先执行R07。</p></details></section>""".replace(
        "FINDINGS", findings
    )
    page = page.replace(
        "<section><h2>逐项预期与实际结果</h2>",
        replay + "<section><h2>逐项预期与实际结果</h2>",
    )
    baseline = (
        '<section><details><summary>模型辅助基线（不计入智能体验收）</summary><div class="tablewrap"><table><thead><tr><th>编号</th><th>类别</th><th>问题</th><th>预期</th><th>状态</th><th>秒</th><th>结果</th></tr></thead><tbody>'
        + "".join(baseline_rows)
        + "</tbody></table></div></details></section>"
    )
    page = page.replace("</div></main>", baseline + "</div></main>")
    (REPORT / "index.html").write_text(
        page.replace(
            "RESULT_COUNT",
            f"智能体主验收 {len(agent_ids)} 项，已测 {len(agent_tested)} 项，通过 {agent_passed} 项；模型辅助基线 {len(matrix['cases']) - len(agent_ids)} 项。完整用例 {len(matrix['cases'])} 项，协议与对话用例执行 {len(executions)} 轮，另存复核 {rechecks} 条；复核不算新执行。",
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
        self.lock = threading.Lock()
        self.memory_cid = None

    def request(self, path, data=None, raw=None, read_bytes=False):
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
            return response.read() if read_bytes else json.load(response)["data"]

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
        link_file = self.root / "web-fixture-links.json"
        self.link_paths = (
            json.loads(link_file.read_text())
            if link_file.exists()
            else {
                "G12": "observations-" + secrets.token_hex(6) + ".html",
                "G13": "update-" + secrets.token_hex(6) + ".html",
            }
        )
        link_file.write_text(json.dumps(self.link_paths))
        (pages / "index.html").write_text(
            '<!doctype html><meta charset="utf-8"><h1>验收观测站</h1><p>旧会议安排：2026-10-20，A馆。</p><a href="'
            + self.link_paths["G12"]
            + '">观测数据</a><a href="'
            + self.link_paths["G13"]
            + '">更正公告</a>'
        )
        (pages / self.link_paths["G12"]).write_text(
            '<!doctype html><meta charset="utf-8"><h1>观测数据</h1><p>北站降水12毫米，南站降水24毫米。统计口径：两站算术平均。</p>'
        )
        (pages / self.link_paths["G13"]).write_text(
            '<!doctype html><meta charset="utf-8"><h1>更正公告</h1><p>最终会议日期为2026-10-22，地点B馆。此前安排作废。</p>'
        )
        handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(
            *args, directory=str(pages), **kwargs
        )
        self.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.web.serve_forever, daemon=True).start()
        self.fixture_url = "http://127.0.0.1:" + str(self.web.server_port)
        seed_document_sources(self)

    def run(self, case):
        start = time.monotonic()
        result = {
            "id": case["id"],
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "status": "未通过",
            "mainParameters": tomllib.loads((self.root / "agent.toml").read_text())
            .get("model", {})
            .get("parameters", {}),
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
            if case.get("document"):
                (self.root / "workspaces" / case["id"]).mkdir(exist_ok=True)
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
            receiver_index = 0 if case["id"] == "D03" else 3
            receiver_file = self.root / f"received-{receiver_index}.jsonl"
            prior_target_messages = (
                sum(
                    json.loads(line) == delivery_marker
                    for line in receiver_file.read_text().splitlines()
                )
                if delivery_marker and receiver_file.exists()
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
            deadline = time.monotonic() + (600 if case.get("document") else 240)
            first_partial = None
            while time.monotonic() < deadline:
                snapshot = self.request("/api/agent/conversations/" + cid + "/messages")
                tasks = self.request("/api/agent/tasks?conversationId=" + cid)
                turns = snapshot["turns"]
                active = any(
                    t["state"] in ["queued", "running"] for t in turns
                ) or bool(
                    self.db(
                        "SELECT id FROM turns WHERE conversation_id=? AND state IN ('queued','running') LIMIT 1",
                        (cid,),
                    )
                )
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
                raise AssertionError("Dialogue exceeded the case deadline")
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
                delivered_lines = [
                    json.loads(line) for line in receiver_file.read_text().splitlines()
                ]
                assert delivered_lines.count(marker) == prior_target_messages + 1, (
                    "Message did not arrive verbatim at the requested recipient"
                )
                result["exactRecipientAndTextVerified"] = True
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
                returned = [
                    json.loads(a["result_json"]) for a in attempts if a["result_json"]
                ]
                directories = [
                    a.get("workspace", {}).get("directory")
                    for a in returned
                    if isinstance(a.get("workspace"), dict)
                ]
                result["executorDirectories"] = directories
                if case["id"] in ["D07", "D10"]:
                    suffix = "codex-loose" if case["id"] == "D07" else "claude-loose"
                    expected = str(self.root / "workspaces" / suffix)
                    assert directories and directories[-1] == expected, (
                        "Executor working directory differs from the user's request"
                    )

                if case["id"] == "D08":
                    assert directories and Path(directories[-1]).is_relative_to(
                        Path(self.state["projectDir"]) / ".worktrees"
                    ), "Project task did not use an isolated project worktree"
                if case["id"] == "D09":
                    assert directories and directories[-1] == str(
                        self.root / "workspaces/acceptance-created"
                    ), "New project executor used a different directory"
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
                assert any(
                    marker in json.dumps(m, ensure_ascii=False) for m in memories
                ), "No active durable memory"
                result["storedMemoryVerified"] = True
                if case.get("memoryMechanism") or case.get("chain") == "memory":
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        preferences = self.db(
                            "SELECT id,revision FROM memory_records WHERE owner_id='local' AND state='active' AND kind='preference' AND conversation_id IS NULL AND body LIKE ?",
                            ("%" + marker + "%",),
                        )
                        if preferences:
                            result["userPreferenceScopeProof"] = preferences
                            break
                        time.sleep(0.4)
                    else:
                        raise AssertionError(
                            "Personal preference was not promoted for automatic cross-conversation recall"
                        )
            if check.get("memoryRecall"):
                validate_memory_recall(self, cid, check["memoryRecall"], result)
            if check.get("discovery"):
                assert "tool_search" in names or "skill_read" in names, (
                    "No actual capability discovery"
                )
            if check.get("followLinkedPage"):
                validate_link_navigation(self, case, cid, result)
            if case.get("memoryMechanism"):
                validate_memory_write(self, cid, check["memory"], result)
            if case.get("document"):
                validate_document_chain(self, case, cid, answer, result)
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
            if result.get("conversationId"):
                result["toolTimeline"] = execution_trace(self, result["conversationId"])
                result["failureEvents"] = self.db(
                    "SELECT kind,payload_json FROM events WHERE conversation_id=? AND kind IN ('turn.failed','turn.interrupted') ORDER BY id",
                    (result["conversationId"],),
                )
            result["seconds"] = round(time.monotonic() - start, 2)
            with (
                self.lock,
                open("/tmp/roami-agent-acceptance-results.lock", "w") as shared_lock,
            ):
                fcntl.flock(shared_lock, fcntl.LOCK_EX)
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
        independent = [c for c in cases if c["id"] not in ["M01", "M02", "R07", "R08"]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(instance.run, independent))
        for case in cases:
            if case["id"] in ["M01", "M02", "R07", "R08"]:
                instance.run(case)
    finally:
        instance.web.shutdown()


if __name__ == "__main__":
    main()
