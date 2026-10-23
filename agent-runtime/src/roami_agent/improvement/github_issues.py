"""One GitHub Issue per complete report; host-owned publication and verified closure."""

import json
import re

from roami_agent.improvement.contracts import digest, load_json, require
from roami_agent.improvement.executors import private_json
from roami_agent.improvement.github_publication import command, profile_path, publication_profile
from roami_agent.improvement.review_report import ISSUE_CATEGORIES


def issue_body(workflow, owner, report, plan):
    priorities = {p["id"]: p["priority"] for p in plan["points"]}
    order = {p["id"]: (p["priority"], i) for i, p in enumerate(plan["points"])}
    categories = {p["id"]: ISSUE_CATEGORIES[p.get("category", "other")] for p in plan["points"]}
    with workflow.ledger.connection() as db:
        items = {
            r["id"]: dict(r)
            for r in db.execute(
                "SELECT id,state,data_json FROM rsi_improvements WHERE owner=?", (owner,)
            )
        }
    lines = [
        "## Roami RSI 复盘 · " + report["day"],
        "",
        "Codex 已逐项复盘整套 60 项任务的指标与执行证据。此 Issue 汇总本轮所有确认的待修点。",
        "",
        "报告 hash：`" + report["sha256"] + "`。完整复盘及原始日志保留在开发机。",
        "",
        "### 修复清单",
        "",
    ]
    closed = []
    for point in sorted(report["points"], key=lambda p: order[p["id"]]):
        f = point["finding"]
        case_id, paths, metric = f["case_id"], f["paths"], f.get("acceptance_metric", "tokens")
        require(
            isinstance(case_id, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", case_id),
            "RSI_INVALID_ISSUE_PLAN",
        )
        require(
            metric in {"tokens", "elapsed_ms", "quality", "repeated_read"}, "RSI_INVALID_ISSUE_PLAN"
        )
        require(
            paths
            and all(
                isinstance(p, str)
                and re.fullmatch(r"agent-runtime/src/roami_agent/[A-Za-z0-9_./-]+", p)
                and ".." not in p.split("/")
                for p in paths
            ),
            "RSI_INVALID_ISSUE_PLAN",
        )
        item = items[digest([owner, point["id"]])]
        done = item["state"] == "closed_fixed"
        closed.append(done)
        lines += [
            f"- [{'x' if done else ' '}] {priorities[point['id']]} · {categories[point['id']]} · `{point['id'][:12]}` · `{case_id}` · 验收指标 `{metric}`",
            "  具体行为、原因假设与改法见开发节点完整复盘；证据摘要：`"
            + digest(f.get("evidence_refs", []))
            + "`。",
            "  修改范围：" + ", ".join("`" + p + "`" for p in paths) + "。",
            "  验收：原问题复测、冻结回归、完整 A/B 和私有门槛通过，后续两个完整周期无退化。",
        ]
        publication = json.loads(item["data_json"]).get("review_publication", {})
        url = publication.get("url")
        if isinstance(url, str) and re.fullmatch(
            r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*", url
        ):
            lines.append("  修复 PR：" + url)
    if not report["points"]:
        lines.append("本轮未发现证据充分的待修点；保留复盘记录，不派发空修复。")
    lines += [
        "",
        "### 执行与关闭",
        "",
        "Codex 复盘 → Codex 汇总此 Issue → Codex 隔离修复 → 程序独立验收 → 草稿 PR → 开发评测实例观察。",
        "",
        "提 PR 不勾选完成；仅独立观察通过的条目勾选完成。全部条目完成后程序关闭 Issue；退化时回滚并重开。普通安装版不执行 RSI。",
    ]
    return "\n".join(lines), (all(closed) if closed else True)


async def publish_issue(workflow, action, plan, *, run=command):
    root = workflow.ledger.path.parent
    profile = publication_profile(root, action["owner"])
    require(profile is not None, "RSI_PUBLICATION_SETUP_REQUIRED")
    report = workflow.report(action["owner"], action["payload"]["cycle_id"])
    require(workflow.report_ready(action["owner"], report), "RSI_EVIDENCE_INCOMPLETE")
    require(plan["report_hash"] == report["sha256"], "RSI_REVIEW_REPORT_CONFLICT")
    slug = profile["repository"]
    marker = "<!-- roami-rsi-report:" + digest([action["owner"], report["cycle_id"]]) + " -->"
    folder = profile_path(root, action["owner"]).parent / "issues" / digest(report["cycle_id"])
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)

    async def call(argv, **kwargs):
        with workflow.ledger.connection() as db:
            workflow._owned_action(db, action)
        return json.loads(await run(["gh", "api", *argv], **kwargs))

    receipt = folder / "receipt.json"
    saved = load_json(receipt) if receipt.exists() else report.get("issue")
    if saved:
        require(
            saved["repository"] == slug and saved["report_hash"] == report["sha256"],
            "RSI_ISSUE_PUBLICATION_CONFLICT",
        )
        issue = await call(["repos/" + slug + "/issues/" + str(saved["number"])])
    else:
        found = await call(
            [
                "--method",
                "GET",
                "search/issues",
                "-f",
                f'q=repo:{slug} is:issue in:body "{marker}"',
                "-f",
                "per_page=100",
            ]
        )
        matches = [
            i
            for i in found.get("items", [])
            if marker in (i.get("body") or "") and not i.get("pull_request")
        ]
        require(len(matches) <= 1, "RSI_ISSUE_PUBLICATION_CONFLICT")
        if matches:
            issue = matches[0]
        else:
            require(
                not (folder / "create-started.json").exists(), "RSI_PUBLICATION_OUTCOME_UNKNOWN"
            )
            private_json(folder / "create-started.json", {"repository": slug, "marker": marker})
            body, _ = issue_body(workflow, action["owner"], report, plan)
            issue = await call(
                ["--method", "POST", "repos/" + slug + "/issues", "--input", "-"],
                data=json.dumps(
                    {
                        "title": "Roami RSI 复盘 · " + report["day"],
                        "body": marker
                        + "\n<!-- rsi-managed:start -->\n"
                        + body
                        + "\n<!-- rsi-managed:end -->",
                    }
                ).encode(),
            )
    number = issue.get("number")
    require(
        type(number) is int
        and number > 0
        and not issue.get("pull_request")
        and issue.get("html_url") == f"https://github.com/{slug}/issues/{number}"
        and marker in (issue.get("body") or ""),
        "RSI_ISSUE_PUBLICATION_CONFLICT",
    )
    verified = await call(["repos/" + slug + "/issues/" + str(number)])
    require(
        verified.get("id") == issue.get("id")
        and verified.get("html_url") == issue["html_url"]
        and marker in (verified.get("body") or ""),
        "RSI_ISSUE_PUBLICATION_CONFLICT",
    )
    value = {
        "repository": slug,
        "number": number,
        "url": issue["html_url"],
        "report_hash": report["sha256"],
        "marker": marker,
        "plan": plan,
    }
    if receipt.exists():
        require(load_json(receipt) == value, "RSI_ISSUE_PUBLICATION_CONFLICT")
    else:
        private_json(receipt, value)
    return {"cycle_id": report["cycle_id"], "issue": value}


async def sync_issue(workflow, action, *, run=command):
    report = workflow.report(action["owner"], action["payload"]["cycle_id"])
    receipt = report["issue"]
    require(receipt is not None, "RSI_ISSUE_PUBLICATION_REQUIRED")
    profile = publication_profile(workflow.ledger.path.parent, action["owner"])
    require(
        profile and profile["repository"] == receipt["repository"], "RSI_ISSUE_PUBLICATION_CONFLICT"
    )
    endpoint = "repos/" + receipt["repository"] + "/issues/" + str(receipt["number"])

    async def call(args, **kwargs):
        with workflow.ledger.connection() as db:
            workflow._owned_action(db, action)
        return json.loads(await run(["gh", "api", *args], **kwargs))

    issue = await call([endpoint])
    original = issue.get("body") or ""
    start, end = "<!-- rsi-managed:start -->", "<!-- rsi-managed:end -->"
    require(
        issue.get("html_url") == receipt["url"]
        and receipt["marker"] in original
        and original.count(start) == original.count(end) == 1
        and original.index(start) < original.index(end),
        "RSI_ISSUE_PUBLICATION_CONFLICT",
    )
    content, closed = issue_body(workflow, action["owner"], report, receipt["plan"])
    body = original.split(start)[0] + start + "\n" + content + "\n" + end + original.split(end)[1]
    state = "closed" if closed else "open"
    if body != original or issue.get("state") != state:
        value = await call(
            ["--method", "PATCH", endpoint, "--input", "-"],
            data=json.dumps({"body": body, "state": state}).encode(),
        )
        require(
            value.get("html_url") == receipt["url"]
            and value.get("body") == body
            and value.get("state") == state,
            "RSI_ISSUE_PUBLICATION_CONFLICT",
        )
    return {"cycle_id": report["cycle_id"], "issue": receipt, "state": state}
