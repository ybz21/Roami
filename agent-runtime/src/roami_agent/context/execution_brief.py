"""Canonical execution guidance with the return channel of the current assignment."""

import json
import shlex
from importlib.resources import files
from pathlib import Path


def execution_prompt(name):
    module = Path(__file__).resolve()
    if module.parents[2].name == "src":
        for directory in (module.parents[4] / "backend/api/prompts", module.parents[3] / "prompts"):
            source = directory / name
            if source.is_file():
                return source.read_text(encoding="utf-8").strip()
    return files("roami_agent").joinpath("prompts", name).read_text(encoding="utf-8").strip()


def execution_guide():
    return execution_prompt("task-execution.md").replace("{{FILE_BASE}}", "/api/file")


def managed_setup(target):
    if target["kind"] == "session":
        return "沿用现有工作区、分支和会话名；只处理本次新增要求，保留已有成果。"
    if target["kind"] == "project" and not target.get("workspaceId"):
        branch = "Git 项目：用 `git branch -m <简短英文kebab-case>` 改本次新建的占位分支名，前缀选 feat/fix。"
    elif target["kind"] == "project":
        branch = "复用已有工作区与分支，不改分支名、不自动 rebase/reset。"
    else:
        branch = "Git 仓库按仓库规则创建任务分支，不直接改主干；非 Git 目录不因开工而初始化。"
    return (
        "1. 核对目录、已有改动和 `git status`（Git 仓库），按仓库约定安装依赖。\n"
        f"2. {branch}\n"
        "3. `roami session rename SESSION_ID <4–12字任务名>` 改侧栏/筛选中的会话展示名；"
        "ID 见末尾执行上下文。"
    )


def managed_handoff(run):
    return execution_prompt("task-report-managed.md").replace(
        "{{REVISION}}", str(run["task_revision"])
    )


def swarm_handoff(cli, swarm, task, run):
    message = {
        "taskId": task["id"],
        "runId": run["id"],
        "taskRevision": run["task_revision"],
        "commandKey": "progress-1",
        "messageKey": "progress-1",
        "kind": "progress",
        "text": "替换为本次实际进展、下一步和阻塞。",
    }
    return (
        execution_prompt("task-report-swarm.md")
        .replace("{{SWARM}}", swarm["swarm_id"])
        .replace("{{MEMBER}}", swarm["member_name"])
        .replace("{{MESSAGE}}", json.dumps(message, ensure_ascii=False, indent=2))
        .replace(
            "{{POST_COMMAND}}",
            shlex.join([cli, "swarm", "post", swarm["swarm_id"], "--file", "MESSAGE.json"]),
        )
        .replace(
            "{{STATUS_COMMAND}}", shlex.join([cli, "swarm", "status", swarm["swarm_id"], "--json"])
        )
    )


def legacy_handoff(command):
    return execution_prompt("task-report-legacy.md").replace("{{REPLY_COMMAND}}", command)
