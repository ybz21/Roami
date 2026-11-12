"""Execution guidance is shared; report channels retain their actual contracts."""

import json
import re
from pathlib import Path

import pytest

from roami_agent.context import execution_brief
from roami_agent.context.execution_brief import (
    execution_guide,
    legacy_handoff,
    managed_handoff,
    managed_setup,
    swarm_handoff,
)
from roami_agent.server.swarm_routes import MemberPost


def test_shared_execution_guide_contains_artifact_and_delivery_requirements():
    source = Path(__file__).resolve().parents[2] / "backend/api/prompts/task-execution.md"
    assert execution_guide() == source.read_text().strip().replace("{{FILE_BASE}}", "/api/file")
    assert "## 产物交付" in execution_guide() and "## 完成回报" in execution_guide()
    assert "[报告（Markdown）](/api/file/tmp/report.md)" in execution_guide()
    assert "![截图](/api/file/tmp/screenshot.png)" in execution_guide()
    assert "{{FILE_BASE}}" not in execution_guide()
    completion = execution_guide().split("## 完成回报", 1)[1]
    template = re.search(r"```markdown\n(.*?)\n```", completion, re.DOTALL)[1]
    assert [line.split("：", 1)[0] for line in template.splitlines()] == [
        "结果",
        "产物",
        "验证",
        "未完成",
    ]
    legacy = legacy_handoff("roami agent reply --dispatch example --file RESULT.json")
    payload = json.loads(re.search(r"```json\n(.*?)\n```", legacy, re.DOTALL)[1])
    assert list(payload) == ["key", "status", "summary"]
    assert [line.split("：", 1)[0] for line in payload["summary"].splitlines()] == [
        "结果",
        "产物",
        "验证",
        "未完成",
    ]


def test_packaged_runtime_reads_guidance_without_source_checkout(tmp_path, monkeypatch):
    expected = execution_guide()
    package = tmp_path / "package"
    (package / "prompts").mkdir(parents=True)
    (package / "prompts/task-execution.md").write_text(expected)
    monkeypatch.setattr(
        execution_brief,
        "__file__",
        str(tmp_path / "installed/site-packages/roami_agent/context/execution_brief.py"),
    )
    monkeypatch.setattr(execution_brief, "files", lambda _: package)
    assert execution_guide() == expected


def test_managed_completion_and_swarm_message_bind_to_current_revision():
    task = {"id": "task-one", "origin_conversation_id": "original-main"}
    run = {"id": "run-two", "task_revision": 2}
    managed = managed_handoff(run)
    assert "任务第 2 版" in managed
    assert "任务、执行及原 Main 已由宿主绑定" in managed
    assert "生命周期回调或执行结果" in managed
    assert "无需另外调用发布产物接口" in managed
    assert "downloadUrl" in managed and "工作区范围" in managed
    assert "Tasks.report(owner, taskId, runId, revision, result)" in managed
    assert "此方法由宿主执行" in managed
    swarm = swarm_handoff(
        "/bin/roami path", {"swarm_id": "team", "member_name": "research"}, task, run
    )
    message = json.loads(re.search(r"```json\n(.*?)\n```", swarm, re.DOTALL)[1])
    report = MemberPost.model_validate(message)
    assert report.taskId == "task-one" and report.runId == "run-two" and report.taskRevision == 2
    assert report.kind == "progress"
    assert "'/bin/roami path' swarm post team --file MESSAGE.json" in swarm
    assert "不能用发一条群聊消息替代交付" in swarm


@pytest.mark.parametrize(
    ("target", "rename_branch", "rename_session"),
    [
        ({"kind": "project", "projectId": "new-project"}, True, True),
        ({"kind": "project", "projectId": "existing", "workspaceId": "existing"}, False, True),
        ({"kind": "new_session", "directory": "/work"}, False, True),
        ({"kind": "session", "sessionId": "existing"}, False, False),
    ],
)
def test_managed_setup_renames_only_new_task_resources(target, rename_branch, rename_session):
    setup = managed_setup(target)
    assert ("git branch -m" in setup) is rename_branch
    assert ("roami session rename SESSION_ID" in setup) is rename_session
    if target["kind"] == "session":
        assert "沿用现有工作区、分支和会话名" in setup
    if target.get("workspaceId"):
        assert "不改分支名" in setup


def test_container_source_tree_uses_copied_canonical_prompts(tmp_path, monkeypatch):
    expected = execution_guide()
    project = tmp_path / "container-runtime"
    (project / "prompts").mkdir(parents=True)
    (project / "prompts/task-execution.md").write_text(expected)
    monkeypatch.setattr(
        execution_brief, "__file__", str(project / "src/roami_agent/context/execution_brief.py")
    )
    assert execution_guide() == expected
