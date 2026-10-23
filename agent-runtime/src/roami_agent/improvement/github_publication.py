"""Opt-in draft PR publication of independently verified development patches."""

import html
import json
import re
from pathlib import Path

from roami_agent.improvement.candidate_checks import checked_evidence
from roami_agent.improvement.contracts import digest, load_json, require
from roami_agent.improvement.executors import private_json
from roami_agent.improvement.source_revision import git
from roami_agent.tools.process import execute


def profile_path(root, owner):
    return Path(root) / "review-publication" / digest(owner)[:24] / "profile.json"


def publication_profile(root, owner):
    path = profile_path(root, owner)
    if not path.exists():
        return None
    require(
        not path.is_symlink() and path.stat().st_mode & 0o077 == 0, "RSI_PRIVATE_PROFILE_REQUIRED"
    )
    value = load_json(path, maximum=65536)
    require(isinstance(value, dict) and set(value) == {"repository", "remote", "base"})
    require(all(isinstance(v, str) for v in value.values()))
    require(
        bool(
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", value["repository"]
            )
        )
    )
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value["remote"])))
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value["base"])))
    require(".." not in value["base"] and "//" not in value["base"])
    return value


def configure_publication(root, owner, value):
    path = profile_path(root, owner)
    require(not path.exists(), "RSI_PUBLICATION_ALREADY_CONFIGURED")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_json(path, value)
    try:
        return publication_profile(root, owner)
    except BaseException:
        path.unlink()
        raise


async def command(argv, *, data=None, timeout=60):
    result = await execute(
        argv, cwd=Path.cwd(), timeout=timeout, input_data=data, max_bytes=2_000_000
    )
    require(result["exitCode"] == 0, "RSI_PUBLICATION_COMMAND_FAILED")
    return result["stdout"]


async def publish_verified(
    workflow, action, revisions, config, settings, *, run=command, validate=checked_evidence
):
    runner = run

    async def run(argv, **kwargs):
        with workflow.ledger.connection() as db:
            workflow._owned_action(db, action)
        return await runner(argv, **kwargs)

    candidate = action["payload"]
    require(
        all(
            isinstance(candidate.get(k), str) and re.fullmatch(r"[a-f0-9]{64}", candidate[k])
            for k in ("candidate_build_hash", "regression_output_hash")
        )
    )
    require(candidate.get("verified_by") == "host_code_verifier_v1", "RSI_VERIFICATION_REQUIRED")
    require(
        candidate.get("comparison", {}).get("eligible_for_promotion") is True,
        "RSI_PROMOTION_REJECTED",
    )
    verified = validate(
        workflow.ledger,
        action["owner"],
        candidate["verification_cycles"],
        {arm: candidate[arm + "_build_hash"] for arm in ("baseline", "candidate")},
    )
    require(verified == candidate["comparison"], "RSI_VERIFICATION_CHANGED")
    profile = publication_profile(workflow.ledger.path.parent, action["owner"])
    require(profile is not None, "RSI_PUBLICATION_SETUP_REQUIRED")
    repo, slug = Path(config["repo"]), profile["repository"]
    remote = (await git(repo, "remote", "get-url", profile["remote"])).strip()
    require(
        remote
        in {
            f"git@github.com:{slug}.git",
            f"https://github.com/{slug}.git",
            f"https://github.com/{slug}",
        },
        "RSI_PUBLICATION_REMOTE_CONFLICT",
    )
    quality_root = profile_path(workflow.ledger.path.parent, action["owner"]).parent / "quality"
    quality_root.mkdir(mode=0o700, exist_ok=True)
    quality = quality_root / (candidate["candidate_build_hash"] + ".json")
    candidate_root = Path(candidate["candidate_root"])
    if not quality.exists():
        await run(
            ["uv", "sync", "--project", str(candidate_root / "agent-runtime"), "--frozen"],
            timeout=600,
        )
        await run(
            ["npm", "--prefix", str(candidate_root / "frontend"), "ci", "--no-audit", "--no-fund"],
            timeout=600,
        )
        await run(
            ["bash", str(candidate_root / "scripts/dev/quality/check.sh"), "quick"], timeout=1200
        )
        private_json(quality, {"build_hash": candidate["candidate_build_hash"], "gate": "quick"})
    candidate = await revisions.seal(candidate)
    full = quality_root / (candidate["candidate_build_hash"] + "-full.json")
    if not full.exists():
        await run(
            ["bash", str(candidate_root / "scripts/dev/quality/check.sh"), "full"], timeout=1200
        )
        private_json(full, {"build_hash": candidate["candidate_build_hash"], "gate": "full"})
    commit = candidate["commit"]
    branch = "rsi/" + digest([candidate["improvement_id"], commit])[:24]
    root = profile_path(workflow.ledger.path.parent, action["owner"]).parent / branch.split("/")[1]
    root.mkdir(mode=0o700, exist_ok=True)
    receipt = root / "receipt.json"
    if receipt.exists():
        saved = load_json(receipt)
        require(
            saved["commit"] == commit and saved["repository"] == slug, "RSI_PUBLICATION_CONFLICT"
        )
        return {**candidate, "review_publication": saved}
    # Check effective push URLs too: pushurl and global rewrites can differ from fetch.
    push_urls = (
        await run(
            ["git", "-C", str(repo), "remote", "get-url", "--push", "--all", profile["remote"]]
        )
    ).splitlines()
    allowed_urls = {
        f"git@github.com:{slug}.git",
        f"https://github.com/{slug}.git",
        f"https://github.com/{slug}",
    }
    require(len(push_urls) == 1 and push_urls[0] in allowed_urls, "RSI_PUBLICATION_REMOTE_CONFLICT")
    # The push is idempotent for this exact commit; it never force-updates a branch.
    await run(["git", "-C", str(repo), "push", profile["remote"], commit + ":refs/heads/" + branch])
    pulls = json.loads(
        await run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                "repos/" + slug + "/pulls",
                "-f",
                "state=all",
                "-f",
                "head=" + slug.split("/")[0] + ":" + branch,
                "-f",
                "base=" + profile["base"],
            ]
        )
    )
    require(isinstance(pulls, list) and len(pulls) <= 1, "RSI_PUBLICATION_CONFLICT")
    body = review_body(candidate)
    if pulls:
        pull = pulls[0]
    else:
        marker = root / "create-started.json"
        require(not marker.exists(), "RSI_PUBLICATION_OUTCOME_UNKNOWN")
        private_json(marker, {"repository": slug, "branch": branch, "commit": commit})
        value = {
            "title": "fix(agent): RSI verified improvement " + branch.split("/")[1][:12],
            "head": branch,
            "base": profile["base"],
            "draft": True,
            "body": body,
        }
        pull = json.loads(
            await run(
                ["gh", "api", "--method", "POST", "repos/" + slug + "/pulls", "--input", "-"],
                data=json.dumps(value).encode(),
            )
        )
    require(pull.get("state") == "open" and pull.get("draft") is True, "RSI_REVIEW_STATE_CHANGED")
    require(
        pull.get("head", {}).get("sha") == commit
        and pull.get("base", {}).get("ref") == profile["base"],
        "RSI_PUBLICATION_CONFLICT",
    )
    number = pull.get("number")
    require(type(number) is int and number > 0)
    require(pull.get("html_url") == f"https://github.com/{slug}/pull/{number}")
    # Capture a real browser rendering of the verified report; raw/private trajectories stay local.
    report = root / "verification.html"
    report.write_text(
        "<!doctype html><html><meta charset=utf-8><title>RSI independent verification</title><h1>RSI independent verification</h1><pre>"
        + html.escape(body)
        + "</pre></html>"
    )
    shot = root / "verification.png"
    await run(
        [
            settings.cli_bin,
            "chrome",
            "screenshot",
            str(shot),
            "--fresh",
            "--goto",
            report.as_uri(),
            "--full",
        ],
        timeout=90,
    )
    require(
        shot.is_file() and shot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"),
        "RSI_REVIEW_SCREENSHOT_REQUIRED",
    )
    await run(
        [
            "env",
            "PR_SHOT_REMOTE=" + profile["remote"],
            "PR_SHOT_BRANCH=pr-shots",
            "PR_SHOT_INIT=0",
            str(repo / "scripts/dev/pr-shot.sh"),
            str(number),
            str(shot),
        ],
        timeout=90,
    )
    final_body = (
        body
        + f"\n\n![独立验收报告](https://raw.githubusercontent.com/{slug}/pr-shots/pr-{number}/verification.png)\n"
    )
    await run(
        ["gh", "api", "--method", "PATCH", f"repos/{slug}/pulls/{number}", "--input", "-"],
        data=json.dumps({"body": final_body}).encode(),
    )
    saved = {
        "repository": slug,
        "commit": commit,
        "branch": branch,
        "number": number,
        "url": pull["html_url"],
        "draft": True,
        "evidence_hash": digest(candidate["comparison"]),
    }
    private_json(receipt, saved)
    return {**candidate, "review_publication": saved}


def review_body(candidate):
    finding = candidate["finding"]
    case = finding.get("case_id", "")
    require(isinstance(case, str) and bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", case)))
    paths = candidate["paths"]
    require(
        isinstance(paths, list)
        and paths
        and all(
            isinstance(p, str)
            and p.startswith("agent-runtime/src/roami_agent/")
            and "\n" not in p
            and "`" not in p
            for p in paths
        )
    )
    return (
        (
            "关联汇总 Issue："
            + candidate["issue"]["url"]
            + " · 条目 `"
            + candidate.get("point_id", "")[:12]
            + "`。\n\n"
            if candidate.get("issue")
            else ""
        )
        + "完整评测在用例 `"
        + case
        + "` 观察到异常。本补丁修改 "
        + ", ".join("`" + p + "`" for p in paths)
        + "，并通过独立服务对原问题、冻结回归及完整 A/B 的验收。\n\n"
        + "- 原问题已复测；质量、交付时间、Token 和私有验证门槛均通过。\n"
        + "- 验证报告 hash：`"
        + digest(candidate["comparison"])
        + "`。\n"
        + "- 回归输出 hash：`"
        + candidate["regression_output_hash"]
        + "`。\n"
        + "- 仅应用到开发评测实例；后续两个完整周期继续观察，退化时回滚并重开问题。\n\n"
        + "此 PR 由 RSI 自动提交为草稿，保留人工审阅和合并。原始日志、隐藏集、凭证及用户记录不上传。"
    )
