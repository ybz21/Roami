import pytest
from test_main_file_image_inputs import main_read as main_read_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_image_evidence import reviewed_images
from roami_agent.storage.transcript_repository import message

main_read = main_read_fixture


async def frozen_fixture(fixture, *, record_images=True):
    runtime, turn, path, read = fixture
    original = await runtime.artifacts.put(
        "local", path.read_bytes(), name="frozen.png", mime_type="image/png"
    )
    value, _ = await read()
    plan, prompt = await runtime.loop.context.build(turn, "Review these frozen pixels.", [], None)
    assert any(
        isinstance(item.get("content"), list)
        and any(part.get("type") == "image_url" for part in item["content"])
        for item in prompt
    )
    if not record_images:
        plan = {**plan, "imageEvidence": []}
    await runtime.manifests.record(
        turn, 1, "isolated-main-image-model", "fixture-wire-hash", plan, [], "main"
    )
    review = await runtime.db.call(
        lambda db: message(
            db,
            turn["conversation_id"],
            turn["branch_id"],
            "assistant",
            {"text": "Review current frozen version"},
            turn_id=turn["id"],
        ),
        write=True,
    )
    binding = {
        "owner": "local",
        "role": "main",
        "conversation": turn["conversation_id"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "assistantMessageId": review,
    }
    required = [{"id": original["id"], "sha256": original["sha256"]}]
    return runtime, turn, binding, required, value


async def test_frozen_pixels_match_genuine_current_main_gateway_read_and_manifest(main_read):
    runtime, _, binding, required, value = await frozen_fixture(main_read)
    before = await runtime.db.call(lambda db: db.execute("SELECT count(*) FROM jobs").fetchone()[0])
    proof = await runtime.db.call(lambda db: reviewed_images(db, binding, required))
    assert len(proof) == 1
    assert proof[0]["artifactId"] == required[0]["id"]
    assert proof[0]["imageReadArtifactId"] == value["fileImage"]["artifactId"]
    assert proof[0]["artifactId"] != proof[0]["imageReadArtifactId"]
    assert proof[0]["sha256"] == required[0]["sha256"]
    assert proof[0]["manifestId"] and proof[0]["toolCallId"]
    assert before == await runtime.db.call(
        lambda db: db.execute("SELECT count(*) FROM jobs").fetchone()[0]
    )


async def test_missing_model_image_evidence_cannot_be_replaced_by_file_metadata(main_read):
    runtime, _, binding, required, _ = await frozen_fixture(main_read, record_images=False)
    with pytest.raises(DomainError, match="PUBLICATION_IMAGE_NOT_REVIEWED"):
        await runtime.db.call(lambda db: reviewed_images(db, binding, required))


@pytest.mark.parametrize(
    "fault",
    [
        "worker",
        "task",
        "owner",
        "conversation",
        "lease",
        "missing_lease",
        "old_assistant",
        "ended",
        "stop",
    ],
)
async def test_review_requires_current_independent_main_identity(main_read, fault):
    runtime, turn, binding, required, _ = await frozen_fixture(main_read)
    if fault == "worker":
        binding["role"] = "worker"
    elif fault == "task":
        binding["taskId"] = "author-task"
    elif fault == "owner":
        binding["owner"] = "other"
    elif fault == "conversation":
        binding["conversation"] = (await runtime.conversations.create("local"))["id"]
    elif fault == "lease":
        binding["leaseEpoch"] += 1
    elif fault == "missing_lease":
        binding.pop("leaseEpoch")
    elif fault == "old_assistant":
        binding["assistantMessageId"] = await runtime.db.call(
            lambda db: db.execute(
                "SELECT assistant_message_id FROM tool_calls WHERE turn_id=? ORDER BY rowid LIMIT 1",
                (turn["id"],),
            ).fetchone()[0]
        )
    elif fault == "ended":
        await runtime.db.call(
            lambda db: db.execute("UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)),
            write=True,
        )
    else:
        await runtime.chat.interrupt("local", turn["conversation_id"], "stop-review")
    with pytest.raises(DomainError):
        await runtime.db.call(lambda db: reviewed_images(db, binding, required))


@pytest.mark.parametrize(
    "fault",
    ["different_pixels", "changed_snapshot_sha", "missing_file_receipt", "delete", "forget"],
)
async def test_names_and_stale_or_missing_image_receipts_cannot_review_frozen_bytes(
    main_read, fault
):
    runtime, turn, binding, required, _value = await frozen_fixture(main_read)
    if fault == "different_pixels":
        other = await runtime.artifacts.put(
            "local", b"different frozen content", name="frozen.png", mime_type="image/png"
        )
        required = [{"id": other["id"], "sha256": other["sha256"]}]
    elif fault == "changed_snapshot_sha":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE prompt_manifests SET parts_json=json_set(parts_json,'$.imageEvidence[0].sha256',?) WHERE turn_id=?",
                ("0" * 64, turn["id"]),
            ),
            write=True,
        )
    elif fault == "missing_file_receipt":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE tool_calls SET state='failed' WHERE turn_id=? AND tool_name='file_read'",
                (turn["id"],),
            ),
            write=True,
        )
    elif fault == "delete":
        await runtime.artifacts.delete("local", required[0]["id"])
    else:
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO memory_tombstones VALUES(?,?,?,1)",
                ("local", required[0]["sha256"], "forgotten-image"),
            ),
            write=True,
        )
    with pytest.raises(DomainError):
        await runtime.db.call(lambda db: reviewed_images(db, binding, required))


async def test_review_rechecks_real_snapshot_bytes_without_changing_their_content(main_read):
    from roami_agent.dispatch.publication_image_review import PublicationImageReview

    runtime, _, binding, required, _ = await frozen_fixture(main_read)
    before, body = await runtime.artifacts.read("local", required[0]["id"])
    proof = await PublicationImageReview(runtime.db, runtime.artifacts).inspect(binding, required)
    assert proof[0]["sha256"] == before["sha256"]
    assert (await runtime.artifacts.read("local", required[0]["id"]))[1] == body


async def test_matching_metadata_does_not_hide_corrupt_image_bytes(main_read):
    from roami_agent.dispatch.publication_image_review import PublicationImageReview

    runtime, _, binding, required, _ = await frozen_fixture(main_read)
    _, path = await runtime.artifacts.verified_path("local", required[0]["id"])
    body = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(b"x" + body[1:])
    with pytest.raises(DomainError, match="ARTIFACT_INTEGRITY_FAILED"):
        await PublicationImageReview(runtime.db, runtime.artifacts).inspect(binding, required)


@pytest.mark.parametrize("main_read", [(False, True)], indirect=True)
async def test_worker_image_capability_never_supplies_main_review_proof(main_read):
    runtime, turn, path, read = main_read
    original = await runtime.artifacts.put(
        "local", path.read_bytes(), name="frozen.png", mime_type="image/png"
    )
    value, _ = await read()
    assert not value.get("fileImage")
    plan, prompt = await runtime.loop.context.build(turn, "Review frozen image", [], None)
    assert not plan.get("imageEvidence")
    assert not any(
        isinstance(item.get("content"), list)
        and any(part.get("type") == "image_url" for part in item["content"])
        for item in prompt
    )
    await runtime.manifests.record(
        turn, 1, "isolated-main-without-images", "fixture-wire-hash", plan, [], "main"
    )
    review = await runtime.db.call(
        lambda db: message(
            db,
            turn["conversation_id"],
            turn["branch_id"],
            "assistant",
            {"text": "Image is unavailable"},
            turn_id=turn["id"],
        ),
        write=True,
    )
    binding = {
        "owner": "local",
        "role": "main",
        "conversation": turn["conversation_id"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "assistantMessageId": review,
    }
    with pytest.raises(DomainError, match="PUBLICATION_IMAGE_NOT_REVIEWED"):
        await runtime.db.call(
            lambda db: reviewed_images(
                db, binding, [{"id": original["id"], "sha256": original["sha256"]}]
            )
        )


async def test_stop_during_file_integrity_check_invalidates_the_review(main_read, monkeypatch):
    from roami_agent.dispatch.publication_image_review import PublicationImageReview

    runtime, turn, binding, required, _ = await frozen_fixture(main_read)
    verify = runtime.artifacts.verified_path
    stopped = False

    async def check(owner, artifact):
        nonlocal stopped
        result = await verify(owner, artifact)
        if not stopped:
            stopped = True
            await runtime.chat.interrupt(owner, turn["conversation_id"], "stop-during-image-review")
        return result

    monkeypatch.setattr(runtime.artifacts, "verified_path", check)
    with pytest.raises(DomainError):
        await PublicationImageReview(runtime.db, runtime.artifacts).inspect(binding, required)
    assert stopped


async def test_earlier_image_input_cannot_replace_latest_model_input(main_read):
    runtime, turn, binding, required, _ = await frozen_fixture(main_read)
    plan, _ = await runtime.loop.context.build(
        turn, "Current prompt no longer contains pixels.", [], None
    )
    await runtime.manifests.record(
        turn,
        2,
        "isolated-main-image-model",
        "later-wire-hash",
        {**plan, "imageEvidence": []},
        [],
        "main",
    )
    with pytest.raises(DomainError, match="PUBLICATION_IMAGE_NOT_REVIEWED"):
        await runtime.db.call(lambda db: reviewed_images(db, binding, required))
