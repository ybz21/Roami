#!/usr/bin/env python3
"""Exercise consecutive intents, stop and trace export on an isolated live runtime."""

import argparse
import functools
import http.server
import json
import secrets
import subprocess
import threading
import time
import tomllib
import urllib.parse
from pathlib import Path

from run import Instance


def wait_for(predicate, timeout=600):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise TimeoutError("Acceptance condition did not settle")


def main(args):
    instance = Instance(args.state)
    pages = instance.root / "weather-fixture"
    pages.mkdir(exist_ok=True)
    beijing_marker, shanghai_marker = (
        "BEIJING-" + secrets.token_hex(3),
        "SHANGHAI-" + secrets.token_hex(3),
    )
    for city, content in [
        ("beijing", "北京测试天气：晴，19度，凭证 " + beijing_marker),
        ("shanghai", "上海测试天气：雨，22度，凭证 " + shanghai_marker),
    ]:
        (pages / (city + ".html")).write_text(
            "<!doctype html><html><head><meta charset='utf-8'></head><body><h1>隔离验收数据，不是真实天气</h1><p>"
            + content
            + "</p></body></html>"
        )

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(pages))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conversation = instance.request(
            "/api/agent/main-conversation", {"requestKey": "intent-latency-main"}
        )
        cid = conversation["id"]
        path = "/api/agent/conversations/" + cid
        run_key = str(time.time_ns())
        started = time.monotonic()
        first = instance.request(
            path + "/messages",
            {
                "requestKey": "intent-beijing-" + run_key,
                "text": f"读取 http://127.0.0.1:{server.server_port}/beijing.html ，告诉我北京的测试天气和凭证。页面是测试数据，只需读取这个页面并简短回答，不要查真实天气。",
            },
        )
        wait_for(
            lambda: instance.db(
                "SELECT id FROM prompt_manifests WHERE turn_id=?", (first["turnId"],)
            ),
            30,
        )
        sent_second = time.monotonic()
        second = instance.request(
            path + "/messages",
            {
                "requestKey": "intent-shanghai-" + run_key,
                "text": f"再读取 http://127.0.0.1:{server.server_port}/shanghai.html ，告诉我上海的测试天气和凭证。"
                + ("上一项北京也继续，分别答复。" if args.repeat_previous else "")
                + "只读取这个测试页面，不要查真实天气。",
            },
        )
        accepted_seconds = time.monotonic() - sent_second

        def settled():
            snapshot = instance.request(path + "/messages")
            texts = "\n".join(
                m["content"].get("text", "")
                for m in snapshot["messages"]
                if m["role"] == "assistant" and m["status"] == "completed"
            )
            active = instance.db(
                "SELECT id FROM turns WHERE conversation_id=? AND state IN ('queued','running')",
                (cid,),
            )
            tasks = instance.request("/api/agent/tasks?conversationId=" + cid)
            idle = not active and all(
                t["state"]
                not in {"queued", "preparing", "running", "verifying", "cancelling"}
                for t in tasks
            )
            if idle and (beijing_marker not in texts or shanghai_marker not in texts):
                raise AssertionError(
                    "Execution settled without both fresh credentials in Main replies"
                )
            if (
                beijing_marker in texts
                and shanghai_marker in texts
                and not active
                and all(
                    t["state"] not in {"queued", "preparing", "running", "verifying"}
                    for t in tasks
                )
            ):
                return snapshot

        snapshot = wait_for(settled)
        answered_seconds = time.monotonic() - started
        task_sources = instance.db(
            "SELECT origin_message_id,intent_json FROM tasks WHERE origin_message_id IN (?,?)",
            (first["messageId"], second["messageId"]),
        )
        assert {first["messageId"], second["messageId"]} <= {
            item["origin_message_id"] for item in task_sources
        }, "Each question needs its own task origin"
        for task in task_sources:
            goal = json.loads(task["intent_json"])["goal"]
            wrong_page = (
                "/shanghai.html"
                if task["origin_message_id"] == first["messageId"]
                else "/beijing.html"
            )
            assert wrong_page not in goal, (
                "Independent question goals must not be merged"
            )
        traces = {}
        for name, receipt in [("beijing", first), ("shanghai", second)]:
            query = urllib.parse.urlencode({"turnId": receipt["turnId"]})
            trace = instance.request("/api/agent/traces?" + query)
            (instance.root / (name + "-trace.json")).write_text(
                json.dumps(trace, ensure_ascii=False, indent=2)
            )
            traces[name] = trace["summary"]
        cli = subprocess.run(
            [
                instance.state["cliBin"],
                "agent",
                "trace",
                "--turn",
                first["turnId"],
                "--format",
                "chrome",
            ],
            env=instance.env,
            check=True,
            capture_output=True,
            text=True,
        )
        export = json.loads(cli.stdout)
        assert export["traceEvents"] and "data" not in export
        (instance.root / "intent-perfetto.json").write_text(cli.stdout)
        stop = instance.request(
            path + "/messages",
            {
                "requestKey": "intent-stop-source-" + run_key,
                "text": "请读取上海测试页面，再向我简短复述一遍，不要创建文件。",
            },
        )
        wait_for(
            lambda: instance.db(
                "SELECT id FROM prompt_manifests WHERE turn_id=?", (stop["turnId"],)
            ),
            30,
        )
        stop_started = time.monotonic()
        stopped = instance.request(
            path + "/messages",
            {"requestKey": "intent-stop-" + run_key, "text": "/stop"},
        )
        wait_for(
            lambda: instance.db(
                "SELECT id FROM turns WHERE id=? AND state='interrupted'",
                (stop["turnId"],),
            ),
            10,
        )
        result = {
            "status": "passed",
            "conversationId": cid,
            "firstTurnId": first["turnId"],
            "secondTurnId": second["turnId"],
            "secondAcceptSeconds": round(accepted_seconds, 3),
            "bothAnswersSeconds": round(answered_seconds, 2),
            "mainParameters": tomllib.loads((instance.root / "agent.toml").read_text())
            .get("model", {})
            .get("parameters", {}),
            "workerParameters": tomllib.loads(
                (instance.root / "agent.toml").read_text()
            )
            .get("worker", {})
            .get("model", {})
            .get("parameters", {}),
            "taskOrigins": [item["origin_message_id"] for item in task_sources],
            "deferred": instance.db(
                "SELECT turn_id,created_ms FROM events WHERE conversation_id=? AND kind='turn.deferred'",
                (cid,),
            ),
            "tasks": [
                {"id": t["id"], "state": t["state"]}
                for t in instance.request("/api/agent/tasks?conversationId=" + cid)
            ],
            "traces": traces,
            "stop": {
                "receipt": stopped,
                "seconds": round(time.monotonic() - stop_started, 3),
            },
            "answers": [
                m["content"].get("text", "")
                for m in snapshot["messages"]
                if m["role"] == "assistant" and m["status"] == "completed"
            ],
            "fixtureOnly": True,
            "root": str(instance.root),
        }
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in [
                        "status",
                        "secondAcceptSeconds",
                        "bothAnswersSeconds",
                        "deferred",
                        "stop",
                    ]
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    except Exception as exc:
        args.output.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "root": str(instance.root),
                    "reason": str(exc)
                    if isinstance(exc, (AssertionError, TimeoutError))
                    else type(exc).__name__,
                    "repeatPrevious": args.repeat_previous,
                    "firstTurnId": first["turnId"] if "first" in locals() else None,
                    "secondTurnId": second["turnId"] if "second" in locals() else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat-previous", action="store_true")
    main(parser.parse_args())
