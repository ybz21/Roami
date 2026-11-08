import pytest
from test_publication_releases import (
    automatic_goal as automatic_goal_fixture,
)
from test_publication_releases import (
    coordination as coordination_fixture,
)
from test_publication_releases import (
    delegated_team as delegated_team_fixture,
)
from test_publication_releases import (
    resource_proof,
    running_release,
)

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.native_submission import NativeSubmission
from roami_agent.publication.post_journal import PostJournal

automatic_goal = automatic_goal_fixture
coordination = coordination_fixture
delegated_team = delegated_team_fixture


@pytest.mark.parametrize("outcome", ["created", "disconnected", "missing_id"])
async def test_native_final_action_has_durable_intent_and_never_repeats(
    coordination, tmp_path, outcome
):
    runtime, service, release, actor = await running_release(coordination, tmp_path)
    journal = PostJournal(
        runtime.db,
        lambda db, binding, release_id: service.admit(
            db, binding, "project-a", release_id, resource_proof
        ),
    )
    calls = []

    class Adapter:
        async def prepare(self, context):
            return {
                key: context[key] for key in ("accountId", "channel", "resourceId", "versionSha256")
            } | {"media": [], "content": {"text": "Frozen text"}, "sceneSignature": "native-scene"}

        async def submit_once(self, context, prepared):
            attempt = await runtime.db.call(
                lambda db: journal.fact(
                    db,
                    actor["owner"],
                    "project-a",
                    "publication-attempt:" + context["rootId"],
                )
            )
            intent = await runtime.db.call(
                lambda db: journal.fact(
                    db,
                    actor["owner"],
                    "project-a",
                    "publication-post_submit:" + attempt["attemptId"],
                )
            )
            assert intent["event"]["phase"] == "post_submit"
            calls.append(prepared)
            if outcome == "disconnected":
                raise ConnectionError("response lost after native action")
            return {"platformId": "123456"} if outcome == "created" else {}

    submission = NativeSubmission(journal, Adapter())
    if outcome == "created":
        result = await submission.submit(actor, release["releaseId"])
        assert result["event"]["platformId"] == "123456"
    elif outcome == "disconnected":
        with pytest.raises(ConnectionError):
            await submission.submit(actor, release["releaseId"])
    else:
        with pytest.raises(DomainError, match="PUBLICATION_PLATFORM_ID_UNKNOWN"):
            await submission.submit(actor, release["releaseId"])
    with pytest.raises(DomainError, match="PUBLICATION_RECONCILIATION_REQUIRED"):
        await submission.submit(actor, release["releaseId"])
    assert len(calls) == 1
