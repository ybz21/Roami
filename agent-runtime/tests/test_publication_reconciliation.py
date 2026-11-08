import hashlib

import httpx
import pytest
from test_publication_post_journal import prepared
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.publication.post_journal import PostJournal
from roami_agent.publication.reconciliation import PostReconciliation
from roami_agent.publication.x_channel import XChannel

coordination = coordination_fixture
delegated_team = delegated_team_fixture


@pytest.mark.parametrize("fault", [None, "unknown", "wrong_author", "changed_bytes", "other_owner"])
async def test_reconciliation_reads_existing_post_and_never_resubmits(coordination, fault):
    runtime, binding, journal, attempt, event, active, context = await prepared(coordination)
    event["requestSha256"] = hashlib.sha256(encoded({"text": "Frozen post"}).encode()).hexdigest()
    await journal.record(binding, attempt, event)
    if fault != "unknown":
        await journal.record(
            binding, attempt, {**event, "phase": "post_created", "platformId": "789"}
        )
    active[0] = False
    calls = []

    def transport(request):
        calls.append(request)
        assert request.method == "GET"
        data = (
            {"id": "12345", "protected": False}
            if request.url.path.endswith("/users/me")
            else {
                "id": "789",
                "author_id": "67890" if fault == "wrong_author" else "12345",
                "text": "Frozen post",
            }
        )
        return httpx.Response(200, json={"data": data})

    async def frozen(current):
        assert current == attempt["context"]
        return {
            "text": "Changed post" if fault == "changed_bytes" else "Frozen post",
            "versionSha256": "a" * 64,
        }

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:

        async def channel(account):
            assert account == "12345"
            return XChannel(client, "fixture-access")

        service = PostReconciliation(runtime.db, channel, frozen)
        args = (
            "bob" if fault == "other_owner" else "alice",
            context["projectId"],
            attempt["context"]["rootId"],
        )
        if fault:
            with pytest.raises(DomainError):
                await service.confirm(*args)
        else:
            first = await service.confirm(*args)
            assert first["state"] == "public" and first["platformId"] == "789"
            assert await service.confirm(*args) == first
    stored = await runtime.db.call(
        lambda db: PostJournal.fact(
            db, "alice", context["projectId"], "publication-public:" + attempt["attemptId"]
        )
    )
    assert (stored is not None) == (fault is None)
    if fault in {"unknown", "changed_bytes", "other_owner"}:
        assert calls == []
    with pytest.raises(DomainError, match="PUBLICATION_RELEASE_STOPPED"):
        await journal.record(binding, attempt, event)


async def test_missing_host_dependencies_do_not_produce_public_fact(coordination):
    runtime, _binding, _journal, attempt, _event, _active, context = await prepared(coordination)
    with pytest.raises(DomainError, match="PUBLICATION_RECONCILIATION_UNAVAILABLE"):
        await PostReconciliation(runtime.db).confirm(
            "alice", context["projectId"], attempt["context"]["rootId"]
        )
