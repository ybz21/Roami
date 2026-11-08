import json

import pytest
from test_publication_versions import prepared
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.dispatch.publication_review import PublicationReview
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
from roami_agent.replies.source_review import SourceReplyReview
from roami_agent.storage.database import row
from roami_agent.storage.publication_versions import freeze_version
from roami_agent.storage.transcript_repository import message

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def review_fixture(value, *, read=True):
    runtime, binding, scope, item, artifacts = await prepared(value)
    version = await runtime.db.call(
        lambda db: freeze_version(
            db, binding, item["id"], scope, artifacts, {"body": artifacts[0]["id"]}
        ),
        write=True,
    )
    turn = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM turns WHERE id=?", (binding["turnId"],))
    )
    turn["owner_id"] = "alice"
    binding["originMessageId"] = await runtime.db.call(
        lambda db: db.execute(
            "SELECT source_message_id FROM swarm_goal_delegations WHERE id=?",
            (scope["delegationId"],),
        ).fetchone()[0]
    )
    if read:
        call = {
            "id": identity(),
            "type": "function",
            "function": {
                "name": "read",
                "arguments": json.dumps({"path": "artifact://" + artifacts[0]["id"]}),
            },
        }
        mid = await runtime.db.call(
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
        await runtime.gateway.invoke(turn, mid, call, "main", {**binding, "toolCallId": call["id"]})
    binding["assistantMessageId"] = await runtime.db.call(
        lambda db: message(
            db,
            turn["conversation_id"],
            turn["branch_id"],
            "assistant",
            {"text": "Independent review decision"},
            turn_id=turn["id"],
        ),
        write=True,
    )
    runtime.reply_review = SourceReplyReview(runtime.db, lambda: None)
    plan, prompt = await runtime.loop.context.build(
        turn, "Review exact publication content.", [], None
    )
    runtime.reply_review.observe_context(turn, prompt, source_ids=plan["modelSourceMessageIds"])
    return runtime, binding, version


async def test_independent_review_persists_exact_frozen_content_and_retries(coordination):
    runtime, binding, version = await review_fixture(coordination)
    service = PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review)
    result = await service.decide(
        binding, version["versionId"], "approved", "Read exact body; approved"
    )
    again = await service.decide(
        binding, version["versionId"], "approved", "Read exact body; approved"
    )
    assert result == again and result["decision"] == "approved"
    assert result["publicationAuthorized"] is False
    with pytest.raises(DomainError, match="PUBLICATION_REVIEW_CONFLICT"):
        await service.decide(binding, version["versionId"], "rejected", "Different decision")


@pytest.mark.parametrize("fault", ["no_read", "lost_prompt", "stop", "wrong_owner", "old_lease"])
async def test_approval_does_not_accept_author_claim_or_stale_main(coordination, fault):
    runtime, binding, version = await review_fixture(coordination, read=fault != "no_read")
    if fault == "lost_prompt":
        runtime.reply_review.contexts[binding["turnId"]]["messages"] = []
    elif fault == "stop":
        await runtime.chat.interrupt("alice", binding["conversation"], "stop")
    elif fault == "wrong_owner":
        binding["owner"] = "other"
    elif fault == "old_lease":
        binding["leaseEpoch"] += 1
    with pytest.raises(DomainError):
        await PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review).decide(
            binding, version["versionId"], "approved", "Claimed review"
        )
    count = await runtime.db.call(
        lambda db: db.execute("SELECT count(*) FROM swarm_publication_reviews").fetchone()[0]
    )
    assert count == 0
