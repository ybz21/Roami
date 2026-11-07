"""Project Main reads retain their host binding before and after file I/O."""

import json
from dataclasses import replace

import pytest
from test_project_okr_conversations import create_goal
from test_project_okr_conversations import project_runtime as project_runtime_fixture

from roami_agent.protocol.errors import DomainError

project_runtime = project_runtime_fixture


@pytest.fixture
async def projects(project_runtime, tmp_path, monkeypatch):
    runtime, _, _ = project_runtime
    roots, bindings = {}, {}
    for project in ("a", "b"):
        root = tmp_path / project
        root.mkdir()
        (root / "AGENTS.md").write_text("Project " + project)
        roots[project] = root
        result = await create_goal(runtime, project=project, key="goal-" + project)
        assert result.status_code == 201, result.text
        bindings[project] = {"owner": "alice", "conversation": result.json()["data"]["id"]}

    async def query(*argv):
        project = argv[2]
        return {"data": {"key": project, "name": project, "dir": str(roots[project])}}

    monkeypatch.setattr(runtime.tools.admission.__self__.targets, "_query", query)
    return runtime, roots, bindings


async def invoke(runtime, binding, name="read", **args):
    return await runtime.tools.invoke(
        {"function": {"name": name, "arguments": json.dumps(args)}}, "main", binding
    )


@pytest.mark.parametrize("absolute", [False, True])
async def test_each_main_reads_its_own_registered_root(projects, absolute):
    runtime, roots, bindings = projects
    for project in roots:
        path = str(roots[project] / "AGENTS.md") if absolute else "AGENTS.md"
        result = await invoke(runtime, bindings[project], path=path)
        assert result["data"] == "Project " + project
        assert "workspace" not in bindings[project]
    with pytest.raises(DomainError, match="WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"):
        await invoke(runtime, bindings["a"], path=str(roots["b"] / "AGENTS.md"))


async def test_home_and_other_owner_do_not_acquire_project_scope(projects):
    runtime, roots, bindings = projects
    home = await runtime.conversations.main("alice")
    with pytest.raises(DomainError, match="WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"):
        await invoke(
            runtime,
            {"owner": "alice", "conversation": home["id"]},
            path=str(roots["a"] / "AGENTS.md"),
        )
    with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
        await invoke(runtime, {**bindings["a"], "owner": "bob"}, path="AGENTS.md")


async def test_main_read_does_not_grant_project_write_or_follow_symlinks(projects):
    runtime, roots, bindings = projects
    await invoke(runtime, bindings["a"], path="AGENTS.md")
    with pytest.raises(DomainError, match="WORKSPACE_REQUIRED"):
        await invoke(
            runtime,
            bindings["a"],
            name="write",
            path="new.txt",
            expectedSha256=None,
            content="Do not write",
        )
    assert not (roots["a"] / "new.txt").exists()
    (roots["a"] / "outside.md").symlink_to(roots["b"] / "AGENTS.md")
    with pytest.raises(DomainError, match="FILE_ACCESS_FAILED"):
        await invoke(runtime, bindings["a"], path="outside.md")


async def test_worker_keeps_original_task_workspace(projects):
    runtime, roots, bindings = projects
    result = await runtime.tools.invoke(
        {"function": {"name": "read", "arguments": '{"path":"AGENTS.md"}'}},
        "worker",
        {**bindings["a"], "taskId": "task", "workspace": {"directory": str(roots["b"])}},
    )
    assert result["data"] == "Project b"


@pytest.mark.parametrize("change", ["unbind", "rebind", "root"])
async def test_scope_changed_during_read_withholds_old_bytes(projects, change):
    runtime, roots, bindings = projects
    original = runtime.tools.registry["file_read"]

    async def read_then_change(args, binding):
        result = await original.handler(args, binding)
        assert result["data"] == "Project a"
        if change == "root":
            roots["a"] = roots["b"]
        elif change == "unbind":
            await runtime.db.call(
                lambda db: db.execute(
                    "DELETE FROM project_okr_conversations WHERE conversation_id=?",
                    (binding["conversation"],),
                ),
                write=True,
            )
        else:
            await runtime.db.call(
                lambda db: db.execute(
                    "UPDATE project_okr_conversations SET project_id='b' WHERE conversation_id=?",
                    (binding["conversation"],),
                ),
                write=True,
            )
        return result

    runtime.tools.registry["file_read"] = replace(original, handler=read_then_change)
    with pytest.raises(DomainError, match="PROJECT_FILE_SCOPE_CHANGED"):
        await invoke(runtime, bindings["a"], path="AGENTS.md")


async def test_binding_change_during_project_lookup_rejected_before_read(projects, monkeypatch):
    runtime, roots, bindings = projects
    reads = []
    original = runtime.tools.registry["file_read"]

    async def read(args, binding):
        reads.append(args)
        return await original.handler(args, binding)

    async def query(*argv):
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE project_okr_conversations SET project_id='b' WHERE conversation_id=?",
                (bindings["a"]["conversation"],),
            ),
            write=True,
        )
        return {"data": {"key": "a", "name": "a", "dir": str(roots["a"])}}

    runtime.tools.registry["file_read"] = replace(original, handler=read)
    monkeypatch.setattr(runtime.tools.admission.__self__.targets, "_query", query)
    with pytest.raises(DomainError, match="PROJECT_FILE_SCOPE_CHANGED"):
        await invoke(runtime, bindings["a"], path="AGENTS.md")
    assert reads == []


async def test_repeated_admission_does_not_silently_rebind_a_planned_read(projects):
    runtime, roots, bindings = projects
    tool, args = runtime.tools.validate(
        {"function": {"name": "read", "arguments": '{"path":"AGENTS.md"}'}}, "main"
    )
    _, admitted = await runtime.tools.admission(tool, args, {**bindings["a"], "role": "main"})
    roots["a"] = roots["b"]
    with pytest.raises(DomainError, match="PROJECT_FILE_SCOPE_CHANGED"):
        await invoke(runtime, admitted, path="AGENTS.md")
