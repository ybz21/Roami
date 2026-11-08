import hashlib
import json

import pytest
import test_swarm_delegations as delegation_cases
from test_main_file_image_inputs import picture
from test_publication_catalog import invoke, prepared_command
from test_publication_manifest import bundle
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.app import Runtime
from roami_agent.dispatch.publication_review import PublicationReview
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
from roami_agent.replies.source_review import SourceReplyReview
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row
from roami_agent.storage.publication_reviews import current_version
from roami_agent.storage.transcript_repository import message

coordination = coordination_fixture


@pytest.fixture
async def delegated_team(store, request, tmp_path, monkeypatch):
    def configured_runtime(database, model):
        return Runtime(
            database,
            model,
            settings=Settings(
                endpoint="http://127.0.0.1:1/v1",
                model="isolated-alt-review",
                model_capabilities={"images": True},
                shell_roots=[tmp_path],
            ),
        )

    monkeypatch.setattr(delegation_cases, "Runtime", configured_runtime)
    async for value in delegated_team_fixture.__wrapped__(store, request):

        async def project_query(*argv):
            assert argv[:3] == ("project", "show", "project-a")
            return {"data": {"key": "project-a", "name": "Isolated project", "dir": str(tmp_path)}}

        monkeypatch.setattr(value[0].tools.admission.__self__.targets, "_query", project_query)
        yield value


async def alt_command(value, root):
    runtime, binding, args = await prepared_command(value, root)
    (root / "card.png").write_bytes(picture())
    (root / "alt.txt").write_text("A sample capability panel, not a live publishing receipt.")
    args["content"] = {
        "body": "post.txt",
        "images": ["card.png"],
        "imageAlts": ["alt.txt"],
    }
    args["accountIdentity"] = "123456789"
    await retain_manifest(runtime, args, root)
    return runtime, binding, args


async def retain_manifest(runtime, args, root):
    value = bundle(args)
    scope = {k: args[k] for k in ("taskId", "revision", "runId")}
    for name in dict.fromkeys(args["content"]["images"] + args["content"]["imageAlts"]):
        body = (root / name).read_bytes()
        value["files"].append(
            {**scope, "path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        )
    reference = await runtime.artifacts.put(
        "alice",
        json.dumps(value).encode(),
        name="manifest.json",
        mime_type="application/json",
        task_id=args["taskId"],
        metadata={
            "kind": "deliverable",
            "runId": args["runId"],
            "provisional": False,
            "sourceFile": str(root / "manifest.json"),
        },
    )

    def retain(db):
        prior = json.loads(
            db.execute(
                "SELECT result_json FROM task_attempts WHERE id=?", (args["runId"],)
            ).fetchone()[0]
        )
        prior["artifactRefs"].append(reference)
        db.execute(
            "UPDATE task_attempts SET result_json=? WHERE id=?",
            (json.dumps(prior), args["runId"]),
        )

    await runtime.db.call(retain, write=True)
    args["manifest"] = {"id": reference["id"], "sha256": reference["sha256"]}


async def main_context(runtime, binding, references, image):
    turn = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM turns WHERE id=?", (binding["turnId"],))
    )
    turn["owner_id"] = "alice"
    for path in [*["artifact://" + r["id"] for r in references], str(image)]:
        call = {
            "id": identity(),
            "type": "function",
            "function": {"name": "read", "arguments": json.dumps({"path": path})},
        }
        mid = await runtime.db.call(
            lambda db, call=call: message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": "", "tool_calls": [call]},
                turn_id=turn["id"],
            ),
            write=True,
        )
        result = await runtime.gateway.invoke(
            turn, mid, call, "main", {**binding, "toolCallId": call["id"]}
        )
        assert "error" not in result
    binding["assistantMessageId"] = await runtime.db.call(
        lambda db: message(
            db,
            turn["conversation_id"],
            turn["branch_id"],
            "assistant",
            {"text": "Review frozen text, image and paired ALT."},
            turn_id=turn["id"],
        ),
        write=True,
    )
    plan, prompt = await runtime.loop.context.build(
        turn, "Review exact publication inputs.", [], None
    )
    attempt = 1 + await runtime.db.call(
        lambda db: db.execute(
            "SELECT COALESCE(MAX(attempt_no),0) FROM prompt_manifests WHERE turn_id=?",
            (turn["id"],),
        ).fetchone()[0]
    )
    await runtime.manifests.record(
        turn, attempt, "isolated-alt-review", "fixture-wire", plan, [], "main"
    )
    reviewer = SourceReplyReview(runtime.db, lambda: None)
    reviewer.observe_context(turn, prompt, source_ids=plan["modelSourceMessageIds"])
    return reviewer


@pytest.mark.parametrize("fault", ["without_images", "extra_alt", "literal_alt"])
async def test_alt_must_pair_with_an_image_without_creating_a_version(
    coordination, tmp_path, fault
):
    runtime, binding, args = await alt_command(coordination, tmp_path)
    if fault == "without_images":
        args["content"].pop("images")
    elif fault == "extra_alt":
        args["content"]["imageAlts"].append("alt.txt")
    else:
        args["content"]["imageAlts"] = ["Literal ALT text is not a manifest path."]
    expected = (
        "PUBLICATION_CONTENT_USE_RELATIVE_MANIFEST_FILE_PATH"
        if fault == "literal_alt"
        else "INVALID_PUBLICATION_IMAGE_ALTS"
    )
    with pytest.raises(DomainError, match=expected):
        await invoke(runtime, binding, args)
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_publication_versions").fetchone()[0]
        )
        == 0
    )


async def test_alt_is_immutable_and_requires_a_real_main_read_before_approval(
    coordination, tmp_path
):
    runtime, binding, args = await alt_command(coordination, tmp_path)
    version = await invoke(runtime, binding, args)
    by_path = {a["path"]: a for a in version["artifacts"]}
    reviewer = await main_context(runtime, binding, [by_path["post.txt"]], tmp_path / "card.png")
    with pytest.raises(DomainError, match="PUBLICATION_TEXT_NOT_REVIEWED"):
        await PublicationReview(runtime.db, runtime.artifacts, reviewer).decide(
            binding, version["versionId"], "approved", "Pixels alone do not review ALT."
        )
    reviewer = await main_context(
        runtime, binding, [by_path["post.txt"], by_path["alt.txt"]], tmp_path / "card.png"
    )
    review = await PublicationReview(runtime.db, runtime.artifacts, reviewer).decide(
        binding, version["versionId"], "approved", "Read image and exact paired ALT."
    )
    assert review["decision"] == "approved" and review["publicationAuthorized"] is False
    saved = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM swarm_publication_reviews WHERE id=?", (review["reviewId"],)
        )
    )
    proof = json.loads(saved["proof_json"])
    assert by_path["alt.txt"]["id"] in {p["artifactId"] for p in proof["text"]}
    assert by_path["card.png"]["id"] == proof["images"][0]["artifactId"]
    before = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM swarm_publication_versions WHERE id=?", (version["versionId"],)
        )
    )
    (tmp_path / "alt.txt").write_text("Revised ALT needs a new approval.")
    await retain_manifest(runtime, args, tmp_path)
    newer = await invoke(runtime, {**binding, "toolCallId": "revised-alt"}, args)
    assert newer["itemId"] == version["itemId"] and newer["sequence"] == version["sequence"] + 1
    with pytest.raises(DomainError, match="PUBLICATION_VERSION_SUPERSEDED"):
        await runtime.db.call(lambda db: current_version(db, binding, version["versionId"]))
    after = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM swarm_publication_versions WHERE id=?", (version["versionId"],)
        )
    )
    assert before == after


async def test_multiple_alts_preserve_the_corresponding_image_order(coordination, tmp_path):
    runtime, binding, args = await alt_command(coordination, tmp_path)
    (tmp_path / "second.png").write_bytes(picture())
    (tmp_path / "second-alt.txt").write_text("The second sample panel.")
    args["content"]["images"] = ["second.png", "card.png"]
    args["content"]["imageAlts"] = ["second-alt.txt", "alt.txt"]
    await retain_manifest(runtime, args, tmp_path)
    version = await invoke(runtime, binding, args)
    by_path = {a["path"]: a for a in version["artifacts"]}
    _, manifest = await runtime.db.call(
        lambda db: current_version(db, binding, version["versionId"])
    )
    assert manifest["content"]["images"] == [by_path[p]["id"] for p in ["second.png", "card.png"]]
    assert manifest["content"]["imageAlts"] == [
        by_path[p]["id"] for p in ["second-alt.txt", "alt.txt"]
    ]


async def test_image_bytes_cannot_be_used_as_alt_text(coordination, tmp_path):
    runtime, binding, args = await alt_command(coordination, tmp_path)
    args["content"]["imageAlts"] = ["card.png"]
    with pytest.raises(DomainError, match="PUBLICATION_ARTIFACT_TYPE_CONFLICT"):
        await invoke(runtime, binding, args)
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_publication_versions").fetchone()[0]
        )
        == 0
    )


async def test_legacy_image_only_review_does_not_claim_an_unselected_alt(coordination, tmp_path):
    runtime, binding, args = await alt_command(coordination, tmp_path)
    args["content"].pop("imageAlts")
    version = await invoke(runtime, binding, args)
    by_path = {a["path"]: a for a in version["artifacts"]}
    assert set(by_path) == {"post.txt", "card.png"}
    reviewer = await main_context(runtime, binding, [by_path["post.txt"]], tmp_path / "card.png")
    review = await PublicationReview(runtime.db, runtime.artifacts, reviewer).decide(
        binding, version["versionId"], "approved", "Legacy body and image only."
    )
    assert review["decision"] == "approved" and review["publicationAuthorized"] is False
