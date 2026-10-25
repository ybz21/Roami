import json
from urllib.parse import quote

import pytest
from test_routing_policy import setup
from test_task_delivery_benchmark import admit, mark

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


async def test_literal_percent_and_space_in_source_names_remain_distinct(store, tmp_path):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Create sources", "sources", executor="codex")
        names = ["part%20one.py", "part one.py"]
        links = []
        for name in names:
            path = tmp_path / name
            path.write_text(name)
            links.append(f"[{name}](/api/file/raw?path={quote(str(path), safe='')})")
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
