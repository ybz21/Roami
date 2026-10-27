import json
from urllib.parse import quote

import pytest
from test_routing_policy import setup
from test_task_delivery_benchmark import admit, mark

from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row
from roami_agent.storage.task_deliverables import read_output, reported_paths


@pytest.mark.parametrize("name", ["app.py", "component.tsx", "main.go"])
def test_source_deliverables_keep_original_bytes_and_discover_bare_paths(tmp_path, name):
    target = tmp_path / name
    body = b"// source retained verbatim\n"
    target.write_bytes(body)
    assert reported_paths(f"Created {target}", str(tmp_path)) == [str(target)]
    assert read_output(tmp_path, str(target), 1000) == (str(target), body)


@pytest.mark.parametrize("legacy_deleted", [False, True])
async def test_source_aliases_share_one_artifact_and_deleted_aliases_cannot_restore_it(
    store, tmp_path, legacy_deleted
):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Create source", "source", executor="codex")
        source = tmp_path / "answer.py"
        source.write_text("print(42)\n")
        url = "/api/file/raw?path=" + quote(str(source), safe="")
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": f"[answer.py]({url}) and {source}",
                "workspace": {"directory": str(tmp_path)},
            },
        )
        detail = await runtime.tasks.get("alice", task["id"])
        references = detail["delivery"]["artifacts"]
        assert len(references) == 1 and not detail["delivery"]["unavailable"]
        artifact = references[0]
        assert (await runtime.artifacts.read("alice", artifact["id"]))[1] == b"print(42)\n"
        if legacy_deleted:
            metadata = {k: v for k, v in artifact["metadata"].items() if k != "sourceFile"}
            unrelated = await runtime.artifacts.put(
                "alice",
                b"other",
                mime_type="text/x-python",
                name="other.py",
                task_id=task["id"],
                metadata={**metadata, "sourcePath": str(tmp_path / "other.py")},
            )
            await runtime.artifacts.delete("alice", unrelated["id"])
            await store.call(
                lambda db: db.execute(
                    "UPDATE artifacts SET metadata_json=? WHERE id=?",
                    (json.dumps(metadata), artifact["id"]),
                ),
                write=True,
            )
        await runtime.artifacts.delete("alice", artifact["id"])
        result = await runtime.tasks.get("alice", task["id"])
        assert not result["delivery"]["artifacts"]
        assert await runtime.artifacts.list("alice", task_id=task["id"]) == []
    finally:
        await runtime.close()


@pytest.mark.parametrize("form", ["segments", "encoded", "extra_slash"])
async def test_svg_serve_aliases_keep_one_snapshot(store, tmp_path, form):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Create plot", "plot", executor="native")
        source = tmp_path / "equity.svg"
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        paths = {
            "segments": "/api/file/serve" + quote(str(source), safe="/"),
            "encoded": "/api/file/serve/" + quote(str(source), safe=""),
            "extra_slash": "/api/file/serve/" + str(source),
        }
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": f"[plot]({paths[form]}) and `{source}`",
                "workspace": {"directory": str(tmp_path)},
            },
        )
        delivery = (await runtime.tasks.get("alice", task["id"]))["delivery"]
        assert len(delivery["artifacts"]) == 1 and not delivery["unavailable"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("relative", [False, True])
async def test_literal_percent_and_space_in_source_names_remain_distinct(store, tmp_path, relative):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Create sources", "sources", executor="codex")
        names = ["part%20one.py", "part one.py"]
        links = []
        for name in names:
            path = tmp_path / name
            path.write_text(name)
            links.append(
                f"`{name}`"
                if relative and " " not in name
                else f"[{name}](/api/file/raw?path={quote(str(path), safe='')})"
            )
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": "\n".join(links),
                "workspace": {"directory": str(tmp_path)},
            },
        )
        detail = await runtime.tasks.get("alice", task["id"])
        references = detail["delivery"]["artifacts"]
        assert {r["name"] for r in references} == set(names)
        assert len(references) == 2
    finally:
        await runtime.close()


@pytest.mark.parametrize("separator", ["\n", r"\n"])
async def test_bold_reported_outputs_with_cjk_notes_are_both_delivered(store, tmp_path, separator):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Create demo", "demo", executor="codex")
        page, readme = tmp_path / "index.html", tmp_path / "README.md"
        page.write_text("<!doctype html><title>Demo</title>")
        readme.write_text("Open index.html offline.")
        summary = separator.join(
            [f"**{page}**（可直接 `file://{page}` 打开）", f"**{readme}**（运行入口）"]
        )
        assert reported_paths(summary, str(tmp_path)) == [str(page), str(readme)]
        assert reported_paths(separator.join([str(page), str(readme)]), str(tmp_path)) == [
            str(page),
            str(readme),
        ]
        await mark(
            runtime,
            task,
            "waiting_user",
            {"state": "succeeded", "summary": summary, "workspace": {"directory": str(tmp_path)}},
        )
        detail = await runtime.tasks.get("alice", task["id"])
        artifacts = detail["delivery"]["artifacts"]
        assert {a["name"] for a in artifacts} == {"index.html", "README.md"}
        assert not detail["delivery"]["unavailable"]
        page.unlink()
        readme.unlink()
        for a in artifacts:
            assert (await runtime.artifacts.read("alice", a["id"]))[1]
    finally:
        await runtime.close()


@pytest.mark.parametrize("executor", ["native", "codex"])
async def test_grouped_relative_generated_outputs_survive_workspace_removal(
    store, tmp_path, executor
):
    runtime, _, _, _, binding = await setup(store)
    bodies = {
        "analysis.py": b"print('finished')\n",
        "result.json": b'{"result":42}\n',
        "trades.csv": b"side,quantity\nbuy,1\n",
        "equity.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 1L1 0"/></svg>',
        "report.md": b"Verified local outputs.\n",
    }
    try:
        task = await admit(
            runtime, binding, "Create analysis outputs", "grouped", executor=executor
        )
        for name, body in bodies.items():
            (tmp_path / name).write_bytes(body)
        summary = f"Files in `{tmp_path}`: " + ", ".join(f"`{name}`" for name in bodies)
        summary += "\nRun `python analysis.py`; do not execute `https://example.test/x.json`."
        await mark(
            runtime,
            task,
            "waiting_user",
            {"state": "succeeded", "summary": summary, "workspace": {"directory": str(tmp_path)}},
        )
        delivery = (await runtime.tasks.get("alice", task["id"]))["delivery"]
        assert not delivery["unavailable"]
        artifacts = delivery["artifacts"]
        assert {a["name"] for a in artifacts} == set(bodies)
        assert (
            next(a for a in artifacts if a["name"] == "equity.svg")["mimeType"] == "image/svg+xml"
        )
        for name in bodies:
            (tmp_path / name).unlink()
        for artifact in artifacts:
            assert (await runtime.artifacts.read("alice", artifact["id"]))[1] == bodies[
                artifact["name"]
            ]
        assert len((await runtime.tasks.get("alice", task["id"]))["delivery"]["artifacts"]) == 5
    finally:
        await runtime.close()


@pytest.mark.parametrize("name", ["../outside.json", "linked.csv", ".hidden.json"])
async def test_relative_reported_outputs_keep_workspace_boundaries(store, tmp_path, name):
    runtime, _, _, _, binding = await setup(store)
    outside = tmp_path.parent / "outside.json"
    outside.write_text("outside")
    (tmp_path / "linked.csv").symlink_to(outside)
    (tmp_path / ".hidden.json").write_text("hidden")
    try:
        task = await admit(runtime, binding, "Report output", "bounded", executor="codex")
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": f"Output `{name}`",
                "workspace": {"directory": str(tmp_path)},
            },
        )
        delivery = (await runtime.tasks.get("alice", task["id"]))["delivery"]
        assert not delivery["artifacts"] and delivery["unavailable"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("mode", ["same_task", "external_edit", "deleted", "other_task"])
async def test_completion_edit_publishes_exact_new_snapshot_only_for_its_task(
    store, tmp_path, mode
):
    runtime, _, _, _, binding = await setup(
        store, settings=Settings(shell_roots=(tmp_path,), coding_directory=tmp_path)
    )
    try:
        task = await admit(runtime, binding, "Create page", "page", executor="codex")
        source = tmp_path / "index.html"
        source.write_text("old")
        result = {
            "state": "succeeded",
            "summary": str(source),
            "workspace": {"directory": str(tmp_path)},
        }
        await mark(runtime, task, "waiting_user", result)
        original = (await runtime.tasks.get("alice", task["id"]))["delivery"]["artifacts"][0]
        callback_task = task
        if mode == "other_task":
            callback_task = await admit(runtime, binding, "Another task", "other", executor="codex")
            await mark(runtime, callback_task, "waiting_user", result)
        raw_task = await store.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (callback_task["id"],))
        )
        attempt = await store.call(
            lambda db: row(
                db, "SELECT * FROM task_attempts WHERE task_id=?", (callback_task["id"],)
            )
        )
        await runtime.dispatch.complete(raw_task, attempt, result, "waiting_user")
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.runId')=?",
                (attempt["id"],),
            )
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET state='completed' WHERE id=?", (binding["turnId"],)
            ),
            write=True,
        )
        turn = await runtime.mailbox.claim(job)
        mid = await runtime.journal.start(turn)
        observed = await runtime.files.read({"path": str(source)}, {})
        value = await runtime.gateway.invoke(
            turn,
            mid,
            {
                "id": "correction",
                "function": {
                    "name": "edit",
                    "arguments": json.dumps(
                        {
                            "path": str(source),
                            "expectedSha256": observed["sha256"],
                            "oldText": "old",
                            "newText": "new",
                        }
                    ),
                },
            },
            "main",
            {**binding, "turnId": turn["id"], "assistantMessageId": mid},
        )
        assert "sha256" in value
        if mode == "external_edit":
            source.write_text("untracked change")
        if mode == "deleted":
            await runtime.artifacts.delete("alice", original["id"])
        delivery = (await runtime.tasks.get("alice", task["id"]))["delivery"]
        if mode in {"external_edit", "deleted"}:
            assert delivery["artifacts"] == [] and delivery["unavailable"]
        elif mode == "other_task":
            assert delivery["artifacts"][0]["id"] == original["id"]
        else:
            current = delivery["artifacts"][0]
            assert current["id"] != original["id"] and current["sha256"] == value["sha256"]
            assert current["metadata"]["sourceUpdate"]["turnId"] == turn["id"]
            assert (await runtime.artifacts.read("alice", original["id"]))[1] == b"old"
            source.unlink()
            assert (await runtime.artifacts.read("alice", current["id"]))[1] == b"new"
            assert (await runtime.tasks.get("alice", task["id"]))["delivery"]["artifacts"][0][
                "id"
            ] == current["id"]
    finally:
        await runtime.close()
