"""File snapshots reach only the active, image-capable Worker through genuine read receipts."""

import base64
import io
import json
import os
from dataclasses import replace

import pytest
from PIL import Image
from test_image_preparation import picture
from test_resource_leases import controller

from roami_agent.app import Runtime
from roami_agent.context.vision_inputs import VisionInputs
from roami_agent.improvement.evaluation.execution.executors import ProtocolFixtureModel
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message


@pytest.fixture
async def image_read(store, tmp_path):
    settings = Settings(
        model_capabilities={"images": True}, image_limits={"max_width": 20, "max_height": 20}
    )
    runtime = Runtime(store, ProtocolFixtureModel([]), settings=settings)
    task, run = await controller(store)
    branch = await store.call(
        lambda db: row(
            db,
            "SELECT b.* FROM branches b JOIN task_attempts r ON r.native_branch_id=b.id WHERE r.id=?",
            (run,),
        )
    )
    tid = identity()
    await store.call(
        lambda db: db.execute(
            "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'user','running',?)",
            (tid, branch["conversation_id"], branch["id"], now_ms()),
        ),
        write=True,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "frame.png").write_bytes(picture(color="red"))
    turn = await store.call(lambda db: row(db, "SELECT * FROM turns WHERE id=?", (tid,)))
    turn.update(
        {
            "owner_id": "alice",
            "executionRunId": run,
            "workspace": {"directory": str(workspace)},
        }
    )

    async def read(path="frame.png", *, role="worker", extra=None, altered_binding=None):
        call = {
            "id": identity(),
            "type": "function",
            "function": {"name": "read", "arguments": json.dumps({"path": path, **(extra or {})})},
        }
        mid = await store.call(
            lambda db: message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": "", "tool_calls": [call]},
                turn_id=tid,
            ),
            write=True,
        )
        binding = {
            "owner": "alice",
            "conversation": turn["conversation_id"],
            "turnId": tid,
            "taskId": task,
            "runId": run,
            "toolCallId": call["id"],
            "workspace": turn["workspace"],
            **(altered_binding or {}),
        }
        value = await runtime.gateway.invoke(turn, mid, call, role, binding)
        return value, {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(value)}

    try:
        yield runtime, turn, task, run, workspace, read
    finally:
        await runtime.close()


def prompt(tool):
    return [
        {"role": "system", "content": "Worker"},
        {"role": "user", "content": "Inspect the file"},
        tool,
    ]


@pytest.mark.parametrize(
    ("format", "suffix", "mime"),
    [("PNG", "png", "image/png"), ("JPEG", "jpg", "image/jpeg"), ("WEBP", "webp", "image/webp")],
)
async def test_real_gateway_read_attaches_model_sized_pixels_without_storing_inline_bytes(
    image_read, format, suffix, mime
):
    runtime, turn, _, _, workspace, read = image_read
    body = picture(format=format)
    path = workspace / ("photo." + suffix)
    path.write_bytes(body)
    value, tool = await read(path.name)
    assert value["contentOmitted"] and value["data"] == ""
    assert value["sha256"] == value["fileImage"]["sha256"]
    reference, stored = await runtime.artifacts.read("alice", value["fileImage"]["artifactId"])
    assert stored == body and reference["mimeType"] == mime
    plan, attached = await runtime.loop.context.vision.attach(
        turn, {"currentTurnStart": 0}, prompt(tool)
    )
    evidence = plan["imageEvidence"][0]
    assert evidence["source"] == "workspace_file" and evidence["optimized"]
    assert evidence["width"] <= 20 and evidence["height"] <= 20
    assert "resourceId" not in evidence and "observationId" not in evidence
    image = attached[-1]["content"][1]["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(image.split(",", 1)[1]))) as decoded:
        assert decoded.size == (evidence["width"], evidence["height"])
    messages = await runtime.db.call(
        lambda db: " ".join(r[0] for r in db.execute("SELECT content_json FROM messages"))
    )
    assert "data:image" not in messages and "data:image" not in json.dumps(plan)
    assert path.read_bytes() == body


@pytest.mark.parametrize("fault", ["owner", "run", "turn", "call", "artifact"])
async def test_a_forged_or_cross_scope_file_image_never_becomes_model_input(image_read, fault):
    runtime, turn, _, _, workspace, read = image_read
    _, tool = await read()
    altered = dict(turn)
    if fault == "owner":
        altered["owner_id"] = "bob"
    if fault == "run":
        altered["executionRunId"] = "another-run"
    if fault == "turn":
        altered["id"] = "another-turn"
    if fault == "call":
        tool["tool_call_id"] = "another-call"
    if fault == "artifact":
        (workspace / "other.png").write_bytes(picture(color="blue"))
        other, _ = await read("other.png")
        value = json.loads(tool["content"])
        value["fileImage"] = other["fileImage"]
        tool["content"] = json.dumps(value)
    original = prompt(tool)
    _, result = await runtime.loop.context.vision.attach(altered, {}, original)
    assert result == original


@pytest.mark.parametrize("fault", ["delete", "forget", "task", "attempt", "revision", "turn"])
async def test_revoked_or_ended_sources_are_not_reused(image_read, fault):
    runtime, turn, task, run, _, read = image_read
    value, tool = await read()
    if fault == "delete":
        await runtime.artifacts.delete("alice", value["fileImage"]["artifactId"])
    elif fault == "forget":
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO memory_tombstones VALUES(?,?,?,1)",
                ("alice", value["sha256"], "file-image"),
            ),
            write=True,
        )
    else:
        sql, args = {
            "task": ("UPDATE tasks SET state='cancelled' WHERE id=?", (task,)),
            "attempt": ("UPDATE task_attempts SET state='cancelled' WHERE id=?", (run,)),
            "revision": ("UPDATE tasks SET revision=revision+1 WHERE id=?", (task,)),
            "turn": ("UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)),
        }[fault]
        await runtime.db.call(lambda db: db.execute(sql, args), write=True)
    original = prompt(tool)
    assert (await runtime.loop.context.vision.attach(turn, {}, original))[1] == original


async def test_deletion_also_revokes_already_prepared_model_and_tool_admission(image_read):
    runtime, turn, _, _, _, read = image_read
    value, tool = await read()
    plan, _ = await runtime.loop.context.vision.attach(turn, {}, prompt(tool))
    await runtime.manifests.record(
        turn, 1, "vision-fixture", "a" * 64, {**plan, "snapshotId": None}, [], "worker"
    )
    await runtime.db.call(lambda db: assert_context_admitted(db, turn))
    await runtime.artifacts.delete("alice", value["fileImage"]["artifactId"])
    with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
        await runtime.db.call(lambda db: assert_context_admitted(db, turn))


async def test_distinct_snapshots_are_attached_and_failed_latest_read_does_not_restore_images(
    image_read,
):
    runtime, turn, _, _, workspace, read = image_read
    first, old = await read()
    (workspace / "next.png").write_bytes(picture(color="blue"))
    second, new = await read("next.png")
    plan, attached = await runtime.loop.context.vision.attach(turn, {}, [*prompt(old), new])
    assert [item["artifactId"] for item in plan["imageEvidence"]] == [
        first["fileImage"]["artifactId"],
        second["fileImage"]["artifactId"],
    ]
    assert len(attached[-1]["content"]) == 4
    (workspace / "invalid.png").write_text("not an image")
    value, invalid = await read("invalid.png")
    assert value["fileImage"]["unavailable"] == "VISION_IMAGE_INVALID"
    original = [*prompt(old), new, invalid]
    assert (await runtime.loop.context.vision.attach(turn, {}, original))[1] == original


@pytest.mark.parametrize("mode", ["main", "text_only", "disabled", "paged", "unbound"])
async def test_nonvisual_reads_and_disabled_read_permission_do_not_capture_pixels(image_read, mode):
    runtime, turn, _, _, _, read = image_read
    role = "main" if mode == "main" else "worker"
    if mode == "text_only":
        runtime.settings.current = replace(runtime.settings.current, model_capabilities={})
    if mode == "disabled":
        runtime.tools.disabled_tools.add("read")
    value, tool = await read(
        role=role,
        extra={"offset": 1} if mode == "paged" else None,
        altered_binding={"runId": None} if mode == "unbound" else None,
    )
    assert not value.get("fileImage", {}).get("artifactId")
    assert (
        await runtime.db.call(lambda db: db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
        == 0
    )
    assert (
        await VisionInputs(runtime.db, runtime.artifacts, runtime.settings).attach(
            turn, {}, prompt(tool)
        )
    )[1] == prompt(tool)


@pytest.mark.parametrize("kind", ["outside", "symlink", "parent_symlink", "directory", "fifo"])
async def test_snapshot_read_keeps_existing_workspace_and_file_type_boundaries(image_read, kind):
    runtime, _, _, _, workspace, read = image_read
    outside = workspace.parent / "outside.png"
    outside.write_bytes(picture())
    path = workspace / "blocked.png"
    if kind == "outside":
        target = "../outside.png"
    elif kind == "parent_symlink":
        (workspace / "linked").symlink_to(workspace.parent, target_is_directory=True)
        target = "linked/outside.png"
    else:
        target = path.name
        if kind == "symlink":
            path.symlink_to(outside)
        elif kind == "directory":
            path.mkdir()
        else:
            os.mkfifo(path)
    value, _ = await read(target)
    assert value["error"] in {
        "WORKSPACE_OUTSIDE_CONFIGURED_ROOTS",
        "FILE_ACCESS_FAILED",
        "FILE_TYPE_OR_SIZE_UNSUPPORTED",
    }
    assert (
        await runtime.db.call(lambda db: db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
        == 0
    )


async def test_source_change_between_page_and_snapshot_is_not_published(image_read, monkeypatch):
    runtime, _, _, _, workspace, read = image_read
    original = runtime.files.snapshot

    async def changed(path, binding, **kwargs):
        (workspace / path).write_bytes(picture(color="blue"))
        return await original(path, binding, **kwargs)

    monkeypatch.setattr(runtime.files, "snapshot", changed)
    value, _ = await read()
    assert value["error"] == "FILE_CHANGED"
    assert (
        await runtime.db.call(lambda db: db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
        == 0
    )


@pytest.mark.parametrize("fault", ["bytes", "pixels"])
async def test_unusable_image_is_metadata_only_without_a_partial_blob(
    image_read, fault, monkeypatch
):
    runtime, turn, _, _, _, read = image_read
    if fault == "bytes":
        runtime.artifacts.max_bytes = 1
    else:
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    value, tool = await read()
    assert value["fileImage"]["unavailable"] in {"VISION_IMAGE_LIMIT", "VISION_IMAGE_INVALID"}
    assert (await runtime.loop.context.vision.attach(turn, {}, prompt(tool)))[1] == prompt(tool)
    assert (
        await runtime.db.call(lambda db: db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
        == 0
    )


async def test_read_snapshot_is_not_automatically_a_task_deliverable(image_read):
    runtime, _, task, run, _, read = image_read
    value, _ = await read()
    assert await runtime.artifacts.for_attempt("alice", task, run, reported_text="Inspected") == []
    explicit = "/api/agent/artifacts/" + value["fileImage"]["artifactId"] + "/content"
    assert (await runtime.artifacts.for_attempt("alice", task, run, reported_text=explicit))[0][
        "id"
    ] == value["fileImage"]["artifactId"]


async def test_native_loop_delivers_file_pixels_to_the_worker_and_keeps_only_references(image_read):
    runtime, turn, task, _, _, _ = image_read

    class VisualWorker:
        model = "workspace-vision-fixture"
        images = 0
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            assert self.calls <= 2, "The read image did not reach the next model request"
            if isinstance(messages[-1].get("content"), list):
                body = base64.b64decode(
                    messages[-1]["content"][1]["image_url"]["url"].split(",", 1)[1]
                )
                with Image.open(io.BytesIO(body)) as image:
                    assert image.getpixel((0, 0)) == (255, 0, 0)
                self.images += 1
                yield ModelEvent("text", "The image is red.")
            else:
                assert "read" in {t["function"]["name"] for t in tools}
                yield ModelEvent(
                    "tool",
                    {
                        "id": "actual-image-read",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({"path": "frame.png"}),
                        },
                    },
                )
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 10,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    worker = VisualWorker()
    runtime.loop.worker_model = worker
    result = await runtime.loop.run(turn, "worker", task_id=task)
    assert result == "The image is red." and worker.images == 1
    values = await runtime.db.call(lambda db: list(db.execute("SELECT content_json FROM messages")))
    assert all("data:image" not in r[0] for r in values)
    manifest = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no DESC LIMIT 1",
            (turn["id"],),
        )
    )
    assert json.loads(manifest["parts_json"])["imageEvidence"][0]["source"] == "workspace_file"
