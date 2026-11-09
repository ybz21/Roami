import httpx
import pytest
from test_publication_post_journal import prepared as journal_fixture
from test_publication_releases import automatic_goal as automatic_goal_fixture
from test_publication_releases import coordination as coordination_fixture
from test_publication_releases import delegated_team as delegated_team_fixture
from test_publication_releases import resource_proof, running_release

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.bilibili_public import BilibiliPublic
from roami_agent.publication.native_reconciliation import NativeReconciliation
from roami_agent.publication.native_submission import NativeSubmission
from roami_agent.publication.post_journal import PostJournal

automatic_goal = automatic_goal_fixture
coordination = coordination_fixture
delegated_team = delegated_team_fixture


@pytest.mark.parametrize(
    "fault", [None, "content", "media", "version", "author", "unknown", "owner"]
)
async def test_native_fact_requires_frozen_content_and_readback(coordination, tmp_path, fault):
    runtime, service, release, actor = await running_release(coordination, tmp_path)
    journal = PostJournal(
        runtime.db,
        lambda db, binding, release_id: service.admit(
            db,
            binding,
            "project-a",
            release_id,
            resource_proof,
        ),
    )
    attempt = await journal.reserve(actor, release["releaseId"])
    frozen = {
        "versionSha256": release["manifestSha256"],
        "content": {"text": "Frozen text"},
        "media": [],
    }

    class Adapter:
        async def prepare(self, context):
            return {
                **frozen,
                **{key: context[key] for key in ("accountId", "channel", "resourceId")},
            }

        async def submit_once(self, context, prepared):
            if fault == "unknown":
                raise ConnectionError("unknown native result")
            return {"platformId": "123456"}

    if fault == "unknown":
        with pytest.raises(ConnectionError):
            await NativeSubmission(journal, Adapter()).submit(actor, release["releaseId"])
    else:
        await NativeSubmission(journal, Adapter()).submit(actor, release["releaseId"])
    if fault in {"content", "media", "version"}:
        frozen[{"version": "versionSha256"}.get(fault, fault)] = "changed"
    calls = []

    async def read_frozen(context):
        return frozen

    async def read_public(context, prepared, platform_id):
        calls.append(platform_id)
        return {
            "state": "public",
            "channel": "x",
            "accountId": "wrong" if fault == "author" else "12345",
            "platformId": platform_id,
        }

    reconciliation = NativeReconciliation(runtime.db, read_frozen, read_public)
    args = ("bob" if fault == "owner" else "alice", "project-a", attempt["context"]["rootId"])
    if fault:
        with pytest.raises(DomainError):
            await reconciliation.confirm(*args)
        assert len(calls) == (1 if fault == "author" else 0)
    else:
        fact = await reconciliation.confirm(*args)
        assert fact["state"] == "public" and fact["kind"] == "publication_public_fact"
        assert await reconciliation.confirm(*args) == fact
        assert calls == ["123456"]


async def test_native_bili_submission_joins_real_journal_and_public_http(coordination):
    runtime, actor, journal, _, _, _, context = await journal_fixture(coordination)
    context.update(channel="bilibili", accountId="243999833", resourceId="chrome:original-target")
    attempt = await journal.reserve(actor, context["releaseId"])
    frozen = {
        "versionSha256": context["versionSha256"],
        "content": {
            "title": "Frozen title",
            "description": "Frozen description\n",
        },
        "media": [],
    }

    class Adapter:
        async def prepare(self, scope):
            return {
                **frozen,
                **{key: scope[key] for key in ("accountId", "channel", "resourceId")},
                "platformMedia": {"cid": "43447814557"},
            }

        async def submit_once(self, scope, prepared):
            return {"platformId": "BV1cpWp6FE8f"}

    await NativeSubmission(journal, Adapter()).submit(actor, context["releaseId"])
    calls = []

    def public(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.bilibili.com"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "bvid": "BV1cpWp6FE8f",
                    "owner": {"mid": 243999833},
                    "state": 0,
                    "title": "Frozen title",
                    "desc": "Frozen description",
                    "cid": 43447814557,
                },
            },
        )

    async def read_frozen(scope):
        return frozen

    async with httpx.AsyncClient(transport=httpx.MockTransport(public)) as client:
        service = NativeReconciliation(runtime.db, read_frozen, BilibiliPublic(client).readback)
        first = await service.confirm("alice", context["projectId"], attempt["context"]["rootId"])
        assert first["state"] == "public" and first["accountId"] == "243999833"
        assert (
            await service.confirm("alice", context["projectId"], attempt["context"]["rootId"])
            == first
        )
        assert len(calls) == 1
