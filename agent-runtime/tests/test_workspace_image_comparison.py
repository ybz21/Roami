"""Compare immutable file views without replaying stale, hidden, or revoked snapshots."""

import base64
import io
import json
from dataclasses import replace

import pytest
from native_prompt_messages import dialogue_messages
from PIL import Image
from test_image_preparation import picture
from test_workspace_image_inputs import image_read as workspace_image_fixture
from test_workspace_image_inputs import prompt

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.context_admission import assert_context_admitted

image_read = workspace_image_fixture


async def test_only_six_latest_distinct_paths_are_present_and_pixels_match_labels(image_read):
    runtime, turn, _, _, workspace, read = image_read
    tools, refs = [], []
    for number, color in enumerate(["red", "blue", "green", "yellow", "black", "white", "purple"]):
        name = f"{number}.png"
        (workspace / name).write_bytes(picture(color=color))
        value, tool = await read(name)
        tools.append(tool)
        refs.append(value["fileImage"]["artifactId"])
    plan, payload = await runtime.loop.context.vision.attach(
        turn, {}, [*prompt(tools[0]), *tools[1:]]
    )
    assert [x["artifactId"] for x in plan["imageEvidence"]] == refs[-6:]
    assert [x["path"] for x in plan["imageEvidence"]] == [f"{index}.png" for index in range(1, 7)]
    parts = payload[-1]["content"]
    pixels = []
    for part in parts:
        if part["type"] == "image_url":
            with Image.open(
                io.BytesIO(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))
            ) as image:
                pixels.append(image.getpixel((0, 0)))
    assert pixels == [
        (0, 0, 255),
        (0, 128, 0),
        (255, 255, 0),
        (0, 0, 0),
        (255, 255, 255),
        (128, 0, 128),
    ]
    stored = await runtime.db.call(
        lambda db: [r[0] for r in db.execute("SELECT content_json FROM messages")]
    )
    assert all("data:image" not in value for value in stored) and "data:image" not in json.dumps(
        plan
    )


async def test_rereading_a_canonical_path_replaces_its_old_snapshot(image_read):
    runtime, turn, _, _, workspace, read = image_read
    first, old = await read()
    (workspace / "frame.png").write_bytes(picture(color="blue"))
    latest, new = await read(str(workspace / "./frame.png"))
    assert first["fileImage"]["path"] == latest["fileImage"]["path"] == "frame.png"
    plan, _ = await runtime.loop.context.vision.attach(turn, {}, [*prompt(old), new])
    assert [x["artifactId"] for x in plan["imageEvidence"]] == [latest["fileImage"]["artifactId"]]


async def test_same_basename_in_different_directories_keeps_both_images(image_read):
    runtime, turn, _, _, workspace, read = image_read
    _, old = await read()
    (workspace / "nested").mkdir()
    (workspace / "nested/frame.png").write_bytes(picture(color="blue"))
    _, new = await read("nested/frame.png")
    plan, _ = await runtime.loop.context.vision.attach(turn, {}, [*prompt(old), new])
    assert [x["path"] for x in plan["imageEvidence"]] == ["frame.png", "nested/frame.png"]


async def test_omitted_tool_receipts_are_not_recovered_from_the_database(image_read):
    runtime, turn, _, _, workspace, read = image_read
    _, old = await read()
    (workspace / "next.png").write_bytes(picture(color="blue"))
    value, new = await read("next.png")
    plan, _ = await runtime.loop.context.vision.attach(turn, {}, prompt(new))
    assert [x["artifactId"] for x in plan["imageEvidence"]] == [value["fileImage"]["artifactId"]]
    plan, _ = await runtime.loop.context.vision.attach(
        turn,
        {"currentTurnStart": 2},
        [*prompt(old), {"role": "user", "content": "Current turn"}, new],
    )
    assert [x["artifactId"] for x in plan["imageEvidence"]] == [value["fileImage"]["artifactId"]]


@pytest.mark.parametrize("fault", ["delete", "forget", "invalid", "paged", "missing", "changed"])
async def test_unavailable_newer_version_never_resurrects_an_older_path(
    image_read, fault, monkeypatch
):
    runtime, turn, _, _, workspace, read = image_read
    _, old = await read()
    (workspace / "frame.png").write_bytes(picture(color="blue"))
    latest, recent = await read(extra={"offset": 1} if fault == "paged" else None)
    if fault == "delete":
        await runtime.artifacts.delete("alice", latest["fileImage"]["artifactId"])
    elif fault == "forget":
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO memory_tombstones VALUES(?,?,?,1)",
                ("alice", latest["sha256"], "comparison"),
            ),
            write=True,
        )
    elif fault == "invalid":
        (workspace / "frame.png").write_text("invalid")
        _, recent = await read()
    elif fault == "missing":
        (workspace / "frame.png").unlink()
        value, recent = await read()
        assert value["error"] == "FILE_ACCESS_FAILED"
        assert value["fileImage"]["path"] == "frame.png"
    elif fault == "changed":
        snapshot = runtime.files.snapshot

        async def change(path, binding, **kwargs):
            if path == "frame.png":
                (workspace / path).write_bytes(picture(color="yellow"))
            return await snapshot(path, binding, **kwargs)

        monkeypatch.setattr(runtime.files, "snapshot", change)
        value, recent = await read()
        assert value["error"] == "FILE_CHANGED"
        assert value["fileImage"]["path"] == "frame.png"
    (workspace / "next.png").write_bytes(picture(color="green"))
    value, new = await read("next.png")
    plan, _ = await runtime.loop.context.vision.attach(turn, {}, [*prompt(old), recent, new])
    assert [x["artifactId"] for x in plan["imageEvidence"]] == [value["fileImage"]["artifactId"]]


async def test_forged_path_is_not_used_as_a_receipt_label(image_read):
    runtime, turn, _, _, _, read = image_read
    value, tool = await read()
    value["fileImage"]["path"] = "forged.png"
    tool["content"] = json.dumps(value)
    original = prompt(tool)
    assert (await runtime.loop.context.vision.attach(turn, {}, original))[1] == original


@pytest.mark.parametrize("fault", ["owner", "run", "turn", "call", "artifact"])
async def test_older_comparison_receipt_still_requires_its_original_scope(image_read, fault):
    runtime, turn, _, _, workspace, read = image_read
    first, old = await read()
    (workspace / "next.png").write_bytes(picture(color="blue"))
    second, new = await read("next.png")
    if fault == "owner":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE artifacts SET owner_id='bob' WHERE id=?",
                (first["fileImage"]["artifactId"],),
            ),
            write=True,
        )
    elif fault in {"run", "turn"}:
        key = "runId" if fault == "run" else "turnId"
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE artifacts SET metadata_json=json_set(metadata_json,?,'another') WHERE id=?",
                ("$." + key, first["fileImage"]["artifactId"]),
            ),
            write=True,
        )
    elif fault == "call":
        old["tool_call_id"] = "forged-call"
    else:
        first["fileImage"]["artifactId"] = second["fileImage"]["artifactId"]
        old["content"] = json.dumps(first)
    plan, _ = await runtime.loop.context.vision.attach(turn, {}, [*prompt(old), new])
    assert [item["artifactId"] for item in plan["imageEvidence"]] == [
        second["fileImage"]["artifactId"]
    ]


async def test_legacy_receipt_keeps_single_image_behavior(image_read):
    runtime, turn, _, _, workspace, read = image_read
    _, old = await read()
    (workspace / "next.png").write_bytes(picture(color="blue"))
    value, new = await read("next.png")
    del value["fileImage"]["path"]
    new["content"] = json.dumps(value)

    def legacy(db):
        db.execute(
            "UPDATE artifacts SET metadata_json=json_remove(metadata_json,'$.sourcePath') WHERE id=?",
            (value["fileImage"]["artifactId"],),
        )
        db.execute(
            "UPDATE messages SET content_json=? WHERE id=(SELECT result_message_id FROM tool_calls WHERE idempotency_key=?)",
            (json.dumps({"text": json.dumps(value)}), turn["id"] + ":" + new["tool_call_id"]),
        )

    await runtime.db.call(legacy, write=True)
    plan, _ = await runtime.loop.context.vision.attach(turn, {}, [*prompt(old), new])
    assert len(plan["imageEvidence"]) == 1 and "path" not in plan["imageEvidence"][0]


@pytest.mark.parametrize("latest", [False, True])
async def test_corrupt_blob_is_not_replaced_by_a_different_image(image_read, monkeypatch, latest):
    runtime, turn, _, _, workspace, read = image_read
    first, old = await read()
    (workspace / "next.png").write_bytes(picture(color="blue"))
    second, new = await read("next.png")
    original = runtime.artifacts.read
    blocked = (second if latest else first)["fileImage"]["artifactId"]

    async def damaged(owner, aid):
        if aid == blocked:
            raise DomainError("ARTIFACT_CONTENT_INVALID")
        return await original(owner, aid)

    monkeypatch.setattr(runtime.artifacts, "read", damaged)
    plan, payload = await runtime.loop.context.vision.attach(turn, {}, [*prompt(old), new])
    assert [x["artifactId"] for x in plan["imageEvidence"]] == (
        [] if latest else [second["fileImage"]["artifactId"]]
    )
    assert "unavailable" in json.dumps(payload[-1])


async def test_deleting_any_prepared_comparison_image_revokes_next_operation(image_read):
    runtime, turn, _, _, workspace, read = image_read
    first, old = await read()
    (workspace / "next.png").write_bytes(picture(color="blue"))
    _, new = await read("next.png")
    plan, _ = await runtime.loop.context.vision.attach(turn, {}, [*prompt(old), new])
    await runtime.manifests.record(
        turn, 1, "comparison-fixture", "a" * 64, {**plan, "snapshotId": None}, [], "worker"
    )
    await runtime.db.call(lambda db: assert_context_admitted(db, turn))
    await runtime.artifacts.delete("alice", first["fileImage"]["artifactId"])
    with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
        await runtime.db.call(lambda db: assert_context_admitted(db, turn))


@pytest.mark.parametrize("count", [2, 6])
async def test_native_loop_compares_all_pixels_in_one_model_request(image_read, count):
    runtime, turn, task, _, workspace, _ = image_read
    names = ["frame.png", *[f"next-{index}.png" for index in range(1, count)]]
    for name in names[1:]:
        (workspace / name).write_bytes(picture(color="blue"))

    class ComparisonWorker:
        model = "comparison-fixture"
        calls = 0

        async def stream(self, messages, tools):
            messages = dialogue_messages(messages)
            self.calls += 1
            assert self.calls <= count + 1, "All file snapshots must be visible together"
            if self.calls <= count:
                yield ModelEvent(
                    "tool",
                    {
                        "id": f"compare-{self.calls}",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({"path": names[self.calls - 1]}),
                        },
                    },
                )
            else:
                pixels = []
                for part in messages[-1]["content"]:
                    if part["type"] == "image_url":
                        with Image.open(
                            io.BytesIO(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))
                        ) as image:
                            pixels.append(image.getpixel((0, 0)))
                assert pixels == [(255, 0, 0), *[(0, 0, 255)] * (count - 1)]
                yield ModelEvent("text", "Red then blue.")
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 10,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    worker = ComparisonWorker()
    runtime.loop.worker_model = worker
    assert await runtime.loop.run(turn, "worker", task_id=task) == "Red then blue."


async def test_tight_combined_budget_retains_latest_snapshot_with_audited_source(image_read):
    runtime, turn, _, _, workspace, read = image_read
    adapter = runtime.loop.context.vision.workspace_images
    adapter.settings = replace(adapter.settings.current, image_limits={"max_encoded_bytes": 100})
    tools, refs = [], []
    for index in range(6):
        name = f"{index}.png"
        (workspace / name).write_bytes(picture(size=(1, 1)))
        value, tool = await read(name)
        tools.append(tool)
        refs.append(value["fileImage"]["artifactId"])
    plan, payload = await runtime.loop.context.vision.attach(
        turn, {}, [*prompt(tools[0]), *tools[1:]]
    )
    assert [image["artifactId"] for image in plan["imageEvidence"]] == refs[-1:]
    assert plan["imageEvidence"][0]["path"] == "5.png"
    assert "omitted" in json.dumps(payload[-1])
