import asyncio

import pytest
from test_publication_author_scope import scope_fixture
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.post_journal import PostJournal

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def prepared(value):
    runtime, binding, scope = await scope_fixture(value)
    context = {
        "owner": "alice",
        "projectId": scope["projectId"],
        "swarmId": scope["swarmId"],
        "itemId": "item-a",
        "channel": "x",
        "accountId": "12345",
        "businessKey": "first-post",
        "versionSha256": "a" * 64,
        "releaseId": "release-a",
        "taskId": scope["taskId"],
        "runId": scope["runId"],
    }
    active = [True]

    # This stub isolates persistence; production must supply actual release/dispatch admission.
    def admit(db, current, release):
        if not active[0]:
            raise DomainError("PUBLICATION_RELEASE_STOPPED", 409)
        assert release == "release-a"
        return context

    journal = PostJournal(runtime.db, admit)
    attempt = await journal.reserve(binding, "release-a")
    event = {
        "businessKey": "first-post",
        "accountId": "12345",
        "versionSha256": "a" * 64,
        "requestSha256": "b" * 64,
        "media": [],
        "phase": "post_submit",
    }
    return runtime, binding, journal, attempt, event, active, context


async def test_concurrent_submit_only_one_receipt_authorizes_transport(coordination):
    runtime, binding, journal, attempt, event, _, _ = await prepared(coordination)
    results = await asyncio.gather(
        journal.record(binding, attempt, event),
        journal.record(binding, attempt, event),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, DomainError) for r in results) == 1
    reopened = PostJournal(runtime.db, journal.admit)
    assert await reopened.reserve(binding, "release-a") == attempt
    with pytest.raises(DomainError, match="PUBLICATION_RECONCILIATION_REQUIRED"):
        await reopened.record(binding, attempt, event)


async def test_stop_after_post_does_not_discard_known_platform_id(coordination):
    _runtime, binding, journal, attempt, event, active, _ = await prepared(coordination)
    await journal.record(binding, attempt, event)
    active[0] = False
    created = {
        **event,
        "phase": "post_created",
        "platformId": "789",
        "url": "https://x.com/i/web/status/789",
    }
    first = await journal.record(binding, attempt, created)
    assert (await journal.record(binding, attempt, created)) == first
    assert first["event"]["platformId"] == "789"
    with pytest.raises(DomainError, match="PUBLICATION_RELEASE_STOPPED"):
        await journal.record(binding, attempt, event)


@pytest.mark.parametrize(
    "fault", ["new_run", "new_version", "other_owner", "created_without_submit", "no_admission"]
)
async def test_new_identity_or_unbound_fact_cannot_escape_the_attempt(coordination, fault):
    runtime, binding, journal, attempt, event, _, context = await prepared(coordination)
    if fault == "no_admission":
        with pytest.raises(DomainError, match="PUBLICATION_RELEASE_ADMISSION_UNAVAILABLE"):
            await PostJournal(runtime.db).reserve(binding, "release-a")
        return
    if fault == "created_without_submit":
        with pytest.raises(DomainError, match="PUBLICATION_SUBMISSION_RECEIPT_REQUIRED"):
            await journal.record(
                binding, attempt, {**event, "phase": "post_created", "platformId": "789"}
            )
        return
    if fault == "other_owner":
        with pytest.raises(DomainError):
            await journal.record({**binding, "owner": "bob"}, attempt, event)
        return
    context["runId" if fault == "new_run" else "versionSha256"] = "another"
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await journal.reserve(binding, "release-a")


async def test_real_sqlite_journal_precedes_transport_and_retains_response_after_stop(coordination):
    import httpx

    from roami_agent.publication.x_channel import XChannel

    runtime, binding, journal, attempt, _event, active, _context = await prepared(coordination)
    sent = []

    async def transport(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"id": "12345", "protected": False}})
        written = await runtime.db.call(
            lambda db: PostJournal.fact(
                db,
                "alice",
                attempt["context"]["projectId"],
                "publication-post_submit:" + attempt["attemptId"],
            )
        )
        assert written is not None
        sent.append(str(request.url))
        active[0] = False
        return httpx.Response(201, json={"data": {"id": "789"}})

    async def record(event):
        return await journal.record(binding, attempt, event)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        channel = XChannel(client, "fixture-access")
        results = await asyncio.gather(
            channel.create("12345", "first-post", "a" * 64, "Exact frozen post", [], record),
            channel.create("12345", "first-post", "a" * 64, "Exact frozen post", [], record),
            return_exceptions=True,
        )
    assert len(sent) == 1
    assert (
        sum(isinstance(result, dict) and result["state"] == "accepted" for result in results) == 1
    )
    assert sum(isinstance(result, DomainError) for result in results) == 1
    stored = await runtime.db.call(
        lambda db: PostJournal.fact(
            db,
            "alice",
            attempt["context"]["projectId"],
            "publication-post_created:" + attempt["attemptId"],
        )
    )
    assert stored["event"]["platformId"] == "789"
