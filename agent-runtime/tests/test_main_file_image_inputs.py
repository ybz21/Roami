"""Main file pixels follow saved Main capabilities, independently of the Worker route."""

import base64
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message

RECIPE = json.loads((Path(__file__).parent / "fixtures/main-file-image.json").read_text())


def picture():
    buffer = io.BytesIO()
    Image.new("RGB", (RECIPE["width"], RECIPE["height"]), tuple(RECIPE["color"])).save(
        buffer, "PNG"
    )
    return buffer.getvalue()


class ReadImage:
    model = "local-image-receipt-fixture"

    def __init__(self, path):
        self.path, self.calls, self.pixels = str(path), 0, []

    async def stream(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            yield ModelEvent(
                "tool",
                {
                    "id": "main-read-image",
                    "type": "function",
                    "function": {"name": "read", "arguments": json.dumps({"path": self.path})},
                },
            )
        else:
            for message in messages:
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if part.get("type") == "image_url":
                        body = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
                        with Image.open(io.BytesIO(body)) as image:
                            self.pixels.append(
                                {
                                    "size": image.size,
                                    "color": image.getpixel((0, 0)),
                                    "encoded": len(part["image_url"]["url"].split(",", 1)[1]),
                                }
                            )
            yield ModelEvent("text", "Image observed." if self.pixels else "Image unavailable.")
        yield ModelEvent(
            "usage",
            {"inputTokens": 10, "outputTokens": 1, "requestAttempts": 1, "retryUsageKnown": True},
        )

    async def close(self):
        pass


async def test_real_main_loop_reads_file_pixels_after_saved_main_only_image_enable(store, tmp_path):
    path = tmp_path / "frame.png"
    body = picture()
    path.write_bytes(body)
    main = ReadImage(path)
    runtime = Runtime(
        store,
        main,
        settings=Settings(
            endpoint="http://127.0.0.1:1/v1",
            model="local-image-contract",
            shell_roots=[tmp_path],
            image_limits={"max_width": 20, "max_height": 20},
        ),
    )
    runtime.model_settings.factory = lambda settings, role: (
        main if role == "main" else ReadImage(path)
    )
    try:
        await runtime.model_settings.save(
            "local", {"main": {"images": True}, "worker": {"images": False}}
        )
        assert runtime.settings.route("main").capabilities["images"] is True
        assert runtime.settings.route("worker").capabilities["images"] is False
        conversation = await runtime.conversations.create("local")
        receipt = await runtime.chat.submit(
            "local", conversation["id"], "read-frame", "Read the image at " + str(path)
        )
        job = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE kind='turn.run'"))
        turn = await runtime.mailbox.claim(job)
        result = await runtime.loop.run(turn, "main")
        assert result == "Image observed."
        assert main.calls == 2 and len(main.pixels) == 1
        assert main.pixels[0]["color"] == tuple(RECIPE["color"])
        assert max(main.pixels[0]["size"]) <= 20
        assert path.read_bytes() == body
        saved = await store.call(
            lambda db: " ".join(t[0] for t in db.execute("SELECT content_json FROM messages"))
        )
        assert "data:image" not in saved
        manifest = await store.call(
            lambda db: row(
                db,
                "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no DESC LIMIT 1",
                (receipt["turnId"],),
            )
        )
        evidence = json.loads(manifest["parts_json"])["imageEvidence"]
        assert len(evidence) == 1 and evidence[0]["source"] == "workspace_file"
        assert evidence[0]["path"] == str(path)
    finally:
        await runtime.close()


def image_parts(prompt):
    return [
        part
        for entry in prompt
        if isinstance(entry.get("content"), list)
        for part in entry["content"]
        if part.get("type") == "image_url"
    ]


@pytest.fixture
async def main_read(store, tmp_path, request):
    path = tmp_path / "frame.png"
    path.write_bytes(picture())
    main = ReadImage(path)
    runtime = Runtime(
        store,
        main,
        settings=Settings(
            endpoint="http://127.0.0.1:1/v1", model="local-image-contract", shell_roots=[tmp_path]
        ),
    )
    runtime.model_settings.factory = lambda settings, role: ReadImage(path)
    capabilities = getattr(request, "param", (True, False))
    await runtime.model_settings.save(
        "local", {"main": {"images": capabilities[0]}, "worker": {"images": capabilities[1]}}
    )
    conversation = await runtime.conversations.create("local")
    await runtime.chat.submit(
        "local", conversation["id"], "read-frame", "Read this exact local image: " + str(path)
    )
    job = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE kind='turn.run'"))
    turn = await runtime.mailbox.claim(job)

    async def read(target=None, *, extra=None, changed_binding=None):
        call = {
            "id": identity(),
            "type": "function",
            "function": {
                "name": "read",
                "arguments": json.dumps({"path": str(target or path), **(extra or {})}),
            },
        }
        mid = await store.call(
            lambda db: message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": "", "tool_calls": [call]},
                turn_id=turn["id"],
            ),
            write=True,
        )
        binding = {
            "owner": "local",
            "conversation": turn["conversation_id"],
            "turnId": turn["id"],
            "taskId": None,
            "runId": None,
            "toolCallId": call["id"],
            **(changed_binding or {}),
        }
        value = await runtime.gateway.invoke(turn, mid, call, "main", binding)
        return value, {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(value)}

    try:
        yield runtime, turn, path, read
    finally:
        await runtime.close()


def prompt(tool):
    return [
        {"role": "system", "content": "Main"},
        {"role": "user", "content": "Inspect the explicit file"},
        tool,
    ]


async def attach(runtime, turn, tools):
    return await runtime.loop.context.chat_images.attach(turn, {"currentTurnStart": 0}, tools)


@pytest.mark.parametrize("fault", ["owner", "turn", "call", "path", "artifact", "native"])
async def test_forged_main_file_image_receipt_is_not_model_input(main_read, fault):
    runtime, turn, path, read = main_read
    _, tool = await read()
    altered = dict(turn)
    if fault == "owner":
        altered["owner_id"] = "stranger"
    elif fault == "turn":
        altered["id"] = "unrelated-turn"
    elif fault == "call":
        tool["tool_call_id"] = "unrelated-call"
    elif fault == "native":
        altered["executionRunId"] = "unrelated-native-run"
    else:
        value = json.loads(tool["content"])
        if fault == "path":
            value["fileImage"]["path"] = str(path.parent / "other.png")
        else:
            other = path.parent / "other.png"
            other.write_bytes(picture())
            reference, _ = await read(other)
            value["fileImage"] = reference["fileImage"]
        tool["content"] = json.dumps(value)
    _, result = await attach(runtime, altered, prompt(tool))
    assert not image_parts(result)


@pytest.mark.parametrize("fault", ["delete", "forget", "ended"])
async def test_revoked_or_ended_main_snapshot_is_not_reused(main_read, fault):
    runtime, turn, _, read = main_read
    value, tool = await read()
    assert value["fileImage"]["artifactId"]
    if fault == "delete":
        await runtime.artifacts.delete("local", value["fileImage"]["artifactId"])
    elif fault == "forget":
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO memory_tombstones VALUES(?,?,?,1)",
                ("local", value["sha256"], "main-file-image"),
            ),
            write=True,
        )
    else:
        await runtime.db.call(
            lambda db: db.execute("UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)),
            write=True,
        )
    _, result = await attach(runtime, turn, prompt(tool))
    assert not image_parts(result)


async def test_main_snapshot_deletion_revokes_an_already_admitted_context(main_read):
    runtime, turn, _, read = main_read
    value, tool = await read()
    plan, _ = await attach(runtime, turn, prompt(tool))
    assert plan["imageEvidence"]
    await runtime.manifests.record(
        turn, 1, "fixture", "a" * 64, {**plan, "snapshotId": None}, [], "main"
    )
    await runtime.db.call(lambda db: assert_context_admitted(db, turn))
    await runtime.artifacts.delete("local", value["fileImage"]["artifactId"])
    with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
        await runtime.db.call(lambda db: assert_context_admitted(db, turn))


@pytest.mark.parametrize("main_read", [(False, True)], indirect=True)
async def test_worker_vision_permission_does_not_enable_main_file_pixels(main_read):
    runtime, turn, _, read = main_read
    value, tool = await read()
    assert not value.get("fileImage", {}).get("artifactId")
    assert not image_parts((await attach(runtime, turn, prompt(tool)))[1])
    assert (
        await runtime.db.call(lambda db: db.execute("SELECT count(*) FROM artifacts").fetchone()[0])
        == 0
    )


@pytest.mark.parametrize("mode", ["disabled", "paged", "invalid"])
async def test_main_file_permission_and_unavailable_inputs_do_not_capture(main_read, mode):
    runtime, turn, path, read = main_read
    if mode == "disabled":
        runtime.tools.disabled_tools.add("read")
    if mode == "invalid":
        path.write_text("not an image")
    value, tool = await read(extra={"offset": 1} if mode == "paged" else None)
    assert not value.get("fileImage", {}).get("artifactId")
    assert not image_parts((await attach(runtime, turn, prompt(tool)))[1])
    assert (
        await runtime.db.call(lambda db: db.execute("SELECT count(*) FROM artifacts").fetchone()[0])
        == 0
    )


@pytest.mark.parametrize("kind", ["outside", "symlink", "parent_symlink", "fifo", "directory"])
async def test_main_file_snapshot_keeps_existing_file_scope_boundaries(main_read, kind):
    runtime, turn, path, read = main_read
    outside = path.parent.parent / "outside-image.png"
    outside.write_bytes(picture())
    target = path.parent / "blocked.png"
    if kind == "outside":
        target = outside
    elif kind == "symlink":
        target.symlink_to(outside)
    elif kind == "parent_symlink":
        (path.parent / "linked").symlink_to(path.parent.parent, target_is_directory=True)
        target = path.parent / "linked/outside-image.png"
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.mkdir()
    value, tool = await read(target)
    assert value["error"] in {
        "WORKSPACE_OUTSIDE_CONFIGURED_ROOTS",
        "FILE_ACCESS_FAILED",
        "FILE_TYPE_OR_SIZE_UNSUPPORTED",
    }
    assert not image_parts((await attach(runtime, turn, prompt(tool)))[1])
    assert (
        await runtime.db.call(lambda db: db.execute("SELECT count(*) FROM artifacts").fetchone()[0])
        == 0
    )


async def test_unusable_latest_main_read_never_restores_old_pixels(main_read):
    runtime, turn, path, read = main_read
    _, old = await read()
    path.write_text("unusable replacement")
    _, new = await read()
    plan, result = await attach(runtime, turn, [*prompt(old), new])
    assert not plan["imageEvidence"] and not image_parts(result)
    assert "unavailable" in result[-1]["content"][0]["text"]


async def test_main_upload_and_file_share_one_configured_image_payload(store, tmp_path):
    path = tmp_path / "frame.png"
    path.write_bytes(picture())
    model = ReadImage(path)
    runtime = Runtime(
        store,
        model,
        settings=Settings(
            endpoint="http://127.0.0.1:1/v1",
            model="local-image-contract",
            shell_roots=[tmp_path],
            image_limits={"max_width": 20, "max_height": 20, "max_encoded_bytes": 200},
        ),
    )
    runtime.model_settings.factory = lambda settings, role: (
        model if role == "main" else ReadImage(path)
    )
    try:
        await runtime.model_settings.save(
            "local", {"main": {"images": True}, "worker": {"images": False}}
        )
        other = io.BytesIO()
        Image.new("RGB", (64, 32), (1, 200, 70)).save(other, "PNG")
        upload = await runtime.attachments.upload(
            "local", "uploaded.png", "upload", other.getvalue()
        )
        conversation = await runtime.conversations.create("local")
        await runtime.chat.submit(
            "local",
            conversation["id"],
            "mixed-images",
            "Read the attachment and the file at " + str(path),
            [upload["id"]],
        )
        job = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE kind='turn.run'"))
        turn = await runtime.mailbox.claim(job)
        assert await runtime.loop.run(turn, "main") == "Image observed."
        assert len(model.pixels) == 2
        assert sum(p["encoded"] for p in model.pixels) <= 200
        assert {p["color"] for p in model.pixels} == {tuple(RECIPE["color"]), (1, 200, 70)}
        manifest = await store.call(
            lambda db: row(
                db,
                "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no DESC LIMIT 1",
                (turn["id"],),
            )
        )
        evidence = json.loads(manifest["parts_json"])["imageEvidence"]
        assert len(evidence) == 2 and {e["artifactId"] for e in evidence} >= {upload["id"]}
        assert runtime.settings.route("worker").capabilities["images"] is False
    finally:
        await runtime.close()
