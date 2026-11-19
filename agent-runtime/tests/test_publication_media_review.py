import hashlib
import json

import pytest
from test_publication_media_inputs import media_inputs
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.dispatch.publication_review import PublicationReview
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.publication.approved_assets import approved_assets
from roami_agent.replies.source_review import SourceReplyReview
from roami_agent.storage.database import event
from roami_agent.storage.publication_media_evidence import reviewed_media_images
from roami_agent.storage.transcript_repository import message

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def reviewed(
    fixture,
    *,
    fault=None,
    transcript="Final source speech",
    account=None,
    audio=True,
    source_mime="video/mp4",
):
    runtime, turn, inspected, invoke, binding = await media_inputs(
        fixture, audio=audio, transcript=transcript, account=account, source_mime=source_mime
    )
    manifest = await runtime.db.call(
        lambda db: json.loads(
            db.execute(
                "SELECT manifest_json FROM swarm_publication_versions WHERE id=?",
                (inspected["versionId"],),
            ).fetchone()[0]
        )
    )
    await invoke("read", manifest["content"]["body"])
    if fault != "report":
        await invoke("read", inspected["report"]["id"])
    if fault != "transcript" and inspected.get("transcript"):
        await invoke("read", inspected["transcript"]["id"])
    if fault != "images":
        for image in inspected["images"]:
            await invoke("image", image["id"])
    binding["assistantMessageId"] = await runtime.db.call(
        lambda db: message(
            db,
            turn["conversation_id"],
            turn["branch_id"],
            "assistant",
            {"text": "Independent sampled media review"},
            turn_id=turn["id"],
        ),
        write=True,
    )
    runtime.reply_review = SourceReplyReview(runtime.db, lambda: None)
    plan, prompt = await runtime.loop.context.build(
        turn, "Review these exact frozen bytes", [], None
    )
    if fault != "manifest":
        await runtime.manifests.record(
            turn, 1, "isolated-media-review", "fixture-wire", plan, [], "main"
        )
    runtime.reply_review.observe_context(turn, prompt, source_ids=plan["modelSourceMessageIds"])
    return runtime, binding, inspected


@pytest.mark.parametrize("transcript", ["Final source speech", ""])
async def test_complete_main_media_inputs_can_be_approved_without_publishing(
    coordination, transcript
):
    runtime, binding, inspected = await reviewed(coordination, transcript=transcript)
    value = await PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review).decide(
        binding,
        inspected["versionId"],
        "approved",
        "Reviewed sampled frames and complete final-track transcript",
    )
    assert value["decision"] == "approved" and value["publicationAuthorized"] is False
    stored = await runtime.db.call(
        lambda db: json.loads(
            db.execute(
                "SELECT proof_json FROM swarm_publication_reviews WHERE id=?", (value["reviewId"],)
            ).fetchone()[0]
        )
    )
    assert len(stored["media"]["images"]) == 3
    assert len(stored["media"]["text"]) == 2


@pytest.mark.parametrize("fault", ["report", "transcript", "images", "manifest"])
async def test_missing_independent_media_evidence_never_records_approval(coordination, fault):
    runtime, binding, inspected = await reviewed(coordination, fault=fault)
    with pytest.raises(DomainError):
        await PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review).decide(
            binding, inspected["versionId"], "approved", "Claimed review"
        )
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_publication_reviews").fetchone()[0]
        )
        == 0
    )


@pytest.mark.parametrize("fault", [None, "not_in_model", "not_read_in_turn"])
async def test_native_model_images_must_match_current_media_receipts(coordination, fault):
    runtime, binding, inspected = await reviewed(
        coordination, fault="images" if fault == "not_read_in_turn" else "manifest"
    )
    selected = inspected["images"][:-1] if fault == "not_in_model" else inspected["images"]
    native = {
        "images": [{"mime": image["mimeType"], "sha256": image["sha256"]} for image in selected]
    }

    async def proof():
        return await runtime.db.call(
            lambda db: reviewed_media_images(
                db,
                binding,
                inspected["versionId"],
                [inspected],
                native_input=native,
            )
        )

    if fault:
        with pytest.raises(DomainError, match="PUBLICATION_MEDIA_IMAGE_NOT_REVIEWED"):
            await proof()
    else:
        result = await proof()
        assert [image["artifactId"] for image in result] == [
            image["id"] for image in inspected["images"]
        ]
        assert all(
            image["source"] == "claude_model_input" and image["resultMessageId"] for image in result
        )


async def test_native_media_approval_uses_complete_text_and_current_sample_pixels(coordination):
    runtime, binding, inspected = await reviewed(coordination, fault="manifest", account="12345")

    def native_receipts(db):
        receipts = db.execute(
            "SELECT native_content(m.content_json) FROM tool_calls c JOIN messages m ON m.id=c.result_message_id "
            "WHERE c.turn_id=? AND c.tool_name='artifact_read' AND c.state='succeeded' ORDER BY m.seq",
            (binding["turnId"],),
        ).fetchall()
        proofs = []
        for receipt in receipts:
            body = json.loads(receipt[0])
            call = body["tool_call_id"]
            wrapper = {
                "toolCallId": call,
                "requestId": call,
                "state": "succeeded",
                "result": json.loads(body["text"]),
                "finishedMs": 123,
            }
            event(
                db,
                binding["conversation"],
                "capability.completed",
                wrapper,
                key="capability:" + call + ":result",
                turn_id=binding["turnId"],
            )
            proofs.append(
                {
                    "toolCallId": call,
                    "responseSha256": hashlib.sha256(
                        encoded({"data": wrapper}).encode()
                    ).hexdigest(),
                }
            )
        return proofs

    proof = {
        "providerId": "current-provider",
        "promptId": "current-prompt",
        "requestSha256": "a" * 64,
        "capabilities": await runtime.db.call(native_receipts, write=True),
        "images": [
            {"mime": ref["mimeType"], "sha256": ref["sha256"]} for ref in inspected["images"]
        ],
    }
    assert len(proof["capabilities"]) == len(proof["images"]) == 3
    binding["nativeCapabilityCall"] = {"requestId": "media-review"}

    async def model_input(actual):
        assert actual is binding
        return proof

    review = await PublicationReview(
        runtime.db, runtime.artifacts, None, native_review_input=model_input
    ).decide(
        binding, inspected["versionId"], "approved", "Reviewed the sampled images and final track."
    )
    assert review["decision"] == "approved" and review["publicationAuthorized"] is False
    stored = await runtime.db.call(
        lambda db: json.loads(
            db.execute(
                "SELECT proof_json FROM swarm_publication_reviews WHERE id=?",
                (review["reviewId"],),
            ).fetchone()[0]
        )
    )
    assert len(stored["media"]["text"]) == 2 and len(stored["media"]["images"]) == 3
    assert all(i["source"] == "claude_model_input" for i in stored["media"]["images"])


@pytest.mark.parametrize("fault", [None, "deleted_transcript", "forgotten_sheet"])
async def test_publisher_round_keeps_approved_media_but_never_removed_review_sources(
    coordination, fault
):
    runtime, binding, inspected = await reviewed(coordination, account="12345")
    review = await PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review).decide(
        binding,
        inspected["versionId"],
        "approved",
        "Reviewed final-track transcript and sampled frames",
    )
    scope = await runtime.db.call(
        lambda db: json.loads(
            db.execute(
                "SELECT manifest_json FROM swarm_publication_versions WHERE id=?",
                (inspected["versionId"],),
            ).fetchone()[0]
        )["author"]
    )
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE tasks SET revision=revision+1,state='queued' WHERE id=?", (scope["taskId"],)
        ),
        write=True,
    )

    async def assets():
        return await runtime.db.call(
            lambda db: approved_assets(
                db, "alice", scope, inspected["versionId"], review["reviewId"], "x", "12345"
            )
        )

    before = await assets()
    assert before["reviewMediaArtifacts"] and before["publicationAuthorized"] is False
    if fault == "deleted_transcript":
        await runtime.artifacts.delete("alice", inspected["transcript"]["id"])
    elif fault == "forgotten_sheet":
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO memory_tombstones VALUES(?,?,?,1)",
                ("alice", inspected["images"][0]["sha256"], "forgotten-source"),
            ),
            write=True,
        )
    if fault:
        with pytest.raises(DomainError, match="PUBLICATION_MEDIA_SOURCE_UNAVAILABLE"):
            await assets()
    else:
        assert await assets() == before


@pytest.mark.parametrize("source_mime,audio", [("audio/wav", True), ("video/mp4", False)])
async def test_audio_only_and_silent_video_follow_their_actual_evidence(
    coordination, source_mime, audio
):
    runtime, binding, inspected = await reviewed(coordination, source_mime=source_mime, audio=audio)
    assert bool(inspected["images"]) is source_mime.startswith("video/")
    assert bool(inspected["audio"]) is audio
    value = await PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review).decide(
        binding, inspected["versionId"], "approved", "Reviewed the available final media evidence"
    )
    assert value["decision"] == "approved" and value["publicationAuthorized"] is False


@pytest.mark.parametrize("fault", ["transcript", "sheet", "lease"])
async def test_final_transaction_rejects_evidence_removed_after_io(
    coordination, monkeypatch, fault
):
    import roami_agent.dispatch.publication_review as module

    runtime, binding, inspected = await reviewed(coordination)
    save = module.save_review

    def raced(db, *args):
        if fault == "lease":
            db.execute(
                "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (binding["turnId"],)
            )
        else:
            ref = inspected["transcript"] if fault == "transcript" else inspected["images"][0]
            db.execute("UPDATE artifacts SET deleted_ms=1 WHERE id=?", (ref["id"],))
        return save(db, *args)

    monkeypatch.setattr(module, "save_review", raced)
    with pytest.raises(DomainError):
        await PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review).decide(
            binding, inspected["versionId"], "approved", "Review raced with evidence removal"
        )
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_publication_reviews").fetchone()[0]
        )
        == 0
    )
