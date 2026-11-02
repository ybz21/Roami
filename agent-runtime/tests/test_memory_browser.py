import httpx
import pytest
from test_memory_pipeline import source
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.memory.records import Memories
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


async def test_review_filter_merges_states_before_counting_and_pagination(store):
    memory = Memories(store)
    conversation, receipt, snapshot = await source(store)
    expected = {snapshot["id"]: snapshot["sha256"]}
    ids = set()
    for index in range(12):
        await memory.save(
            "alice",
            f"Conflict {index}",
            "old",
            receipt["messageId"],
            conversation_id=conversation["id"],
        )
        pending = await memory.propose(
            "alice",
            f"Conflict {index}",
            "new",
            [receipt["messageId"]],
            expected_sources=expected,
            conversation_id=conversation["id"],
        )
        candidate = await memory.propose(
            "alice",
            f"Candidate {index}",
            "candidate",
            [receipt["messageId"]],
            expected_sources=expected,
            conversation_id=conversation["id"],
        )
        ids.update([pending["id"], candidate["id"]])
    pages = [
        await memory.catalog.list(
            "alice", state="review", category="knowledge", limit=7, offset=offset
        )
        for offset in [0, 7, 14, 21]
    ]
    assert all(page["total"] == 24 for page in pages)
    returned = [item["id"] for page in pages for item in page["items"]]
    assert len(returned) == len(set(returned)) == 24 and set(returned) == ids
    assert (await memory.catalog.facets("alice"))["reviewCount"] == 24
    assert (await memory.catalog.facets("bob"))["reviewCount"] == 0


async def test_browser_scope_categories_do_not_broaden_recall(store):
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.dispatch.tasks import Tasks

    memory = Memories(store)
    conversation, receipt, _ = await source(store)
    local = await memory.save(
        "alice", "Local", "local", receipt["messageId"], conversation_id=conversation["id"]
    )
    personal = await memory.save("alice", "Personal", "personal", receipt["messageId"])
    project = await memory.save(
        "alice",
        "Project",
        "project",
        receipt["messageId"],
        project_id="project",
        conversation_id=conversation["id"],
    )
    task = await Tasks(store, Conversations(store)).create(
        "alice",
        conversation["id"],
        "Readable task",
        key="task-scope",
        origin_message_id=receipt["messageId"],
    )
    scoped = await memory.save(
        "alice",
        "Task",
        "task",
        receipt["messageId"],
        project_id="project",
        conversation_id=conversation["id"],
        task_id=task["id"],
    )
    for scope, ident in [
        ("personal", personal["id"]),
        ("conversation", local["id"]),
        ("project", project["id"]),
        ("task", scoped["id"]),
    ]:
        result = await memory.catalog.list("alice", scope=scope)
        assert result["total"] == 1 and result["items"][0]["id"] == ident
    facets = await memory.catalog.facets("alice")
    assert facets["task"] == [{"id": task["id"], "name": "Readable task"}]
    assert facets["project"] == [{"id": "project", "name": None}]
    assert facets["conversation"][0]["id"] == conversation["id"]
    assert not await memory.search("bob")
    assert not await memory.search("alice", "personal", conversation_id=conversation["id"])


async def test_browser_detail_and_confirmation_guard_use_live_sources_and_current_version(store):
    memory = Memories(store)
    conversation, receipt, snapshot = await source(store)
    active = await memory.save(
        "alice",
        "Preference",
        "Codex",
        receipt["messageId"],
        conversation_id=conversation["id"],
        kind="preference",
    )
    pending = await memory.propose(
        "alice",
        "Preference",
        "Claude",
        [receipt["messageId"]],
        expected_sources={snapshot["id"]: snapshot["sha256"]},
        conversation_id=conversation["id"],
        kind="preference",
    )
    detail = await memory.details.get("alice", pending["id"])
    assert detail["record"]["state"] == "conflict"
    assert detail["current"]["id"] == active["id"]
    assert detail["canConfirm"]
    assert detail["evidence"][0]["messageId"] == receipt["messageId"]
    with pytest.raises(DomainError, match="MEMORY_CURRENT_CHANGED"):
        await memory.confirm("alice", pending["id"], expected_current_id="stale")
    assert (await memory.get("alice", active["id"]))["body"] == "Codex"
    await store.call(
        lambda db: db.execute(
            "UPDATE messages SET content_json=? WHERE id=?",
            ('{"text":"Changed source"}', receipt["messageId"]),
        ),
        write=True,
    )
    detail = await memory.details.get("alice", pending["id"])
    assert not detail["canConfirm"] and not detail["evidence"][0]["unchanged"]
    with pytest.raises(DomainError, match="MEMORY_SOURCE_CHANGED"):
        await memory.confirm("alice", pending["id"], expected_current_id=active["id"])
    with pytest.raises(DomainError, match="MEMORY_NOT_FOUND"):
        await memory.details.get("bob", pending["id"])


async def test_browser_history_keeps_only_owned_versions_and_exact_merged_copies(store):
    runtime = Runtime(store, ConversationModel())
    conversation = await runtime.conversations.create("alice")
    receipt = await runtime.conversations.accept(
        "alice", conversation["id"], "remember", "记住：以后首选 Codex"
    )
    local = (await runtime.memory.search("alice"))[0]
    current = await runtime.memory.save(
        "alice", "Executor", "记住：以后首选 Codex", receipt["messageId"], kind="preference"
    )
    unrelated = await runtime.memory.save(
        "alice",
        "Other preference",
        "其他事实",
        receipt["messageId"],
        conversation_id=conversation["id"],
        kind="preference",
    )
    _, foreign_source, _ = await source(store, owner="bob")
    foreign = await runtime.memory.save(
        "bob", "Private", "private", foreign_source["messageId"], kind="preference"
    )

    def seed(db):
        for parent in (local, unrelated, foreign):
            db.execute("INSERT INTO memory_edges VALUES(?,?)", (parent["id"], current["id"]))
            db.execute("UPDATE memory_records SET state='superseded' WHERE id=?", (parent["id"],))

    await store.call(seed, write=True)
    result = await runtime.memory.details.history("alice", current["id"])
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == local["id"] and result["items"][0]["relation"] == "merged"
    newer = await runtime.memory.save(
        "alice", "Executor", "现在首选 Claude", receipt["messageId"], kind="preference"
    )
    result = await runtime.memory.details.history("alice", newer["id"])
    assert {item["id"] for item in result["items"]} == {local["id"], current["id"]}
    await runtime.memory.forget("alice", newer["id"])
    with pytest.raises(DomainError, match="MEMORY_NOT_FOUND"):
        await runtime.memory.details.history("alice", newer["id"])


async def test_missing_sources_keep_browser_body_but_cannot_be_confirmed(store):
    memory = Memories(store)
    conversation, receipt, snapshot = await source(store)
    pending = await memory.propose(
        "alice",
        "Source",
        "Keep the body",
        [receipt["messageId"]],
        expected_sources={snapshot["id"]: snapshot["sha256"]},
        conversation_id=conversation["id"],
    )
    await store.call(
        lambda db: db.execute(
            "UPDATE messages SET deleted_ms=1 WHERE id=?", (receipt["messageId"],)
        ),
        write=True,
    )
    detail = await memory.details.get("alice", pending["id"])
    assert detail["record"]["body"] == "Keep the body"
    assert not detail["canConfirm"] and detail["evidence"][0]["available"] is False
    with pytest.raises(DomainError, match="MEMORY_SOURCE_NOT_FOUND"):
        await memory.confirm("alice", pending["id"])


async def test_browser_http_detail_review_facets_history_and_confirmation(store):
    runtime = Runtime(store, ConversationModel())
    conversation, receipt, snapshot = await source(store)
    saved = await runtime.memory.save(
        "alice",
        "Executor",
        "Codex",
        receipt["messageId"],
        kind="preference",
        conversation_id=conversation["id"],
    )
    pending = await runtime.memory.propose(
        "alice",
        "Executor",
        "Claude",
        [receipt["messageId"]],
        kind="preference",
        conversation_id=conversation["id"],
        expected_sources={snapshot["id"]: snapshot["sha256"]},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        assert (
            await client.get(
                "/v1/memories/catalog?state=review&scope=conversation&category=knowledge"
            )
        ).json()["data"]["total"] == 1
        assert (await client.get("/v1/memories/facets?state=review")).json()["data"][
            "reviewCount"
        ] == 1
        path = "/v1/memories/" + pending["id"]
        assert (await client.get(path + "/detail")).json()["data"]["current"]["id"] == saved["id"]
        assert (
            await client.get(path + "/detail", headers={"X-Roami-Owner": "bob"})
        ).status_code == 404
        response = await client.post(
            path + "/confirm", json={"accepted": True, "expectedCurrentId": "stale"}
        )
        assert response.status_code == 409
        response = await client.post(
            path + "/confirm", json={"accepted": True, "expectedCurrentId": saved["id"]}
        )
        assert response.status_code == 200
        active = response.json()["data"]
        history = (await client.get("/v1/memories/" + active["id"] + "/history")).json()["data"]
        assert any(item["id"] == saved["id"] for item in history["items"])
        stored = await store.call(
            lambda db: row(db, "SELECT state FROM memory_records WHERE id=?", (pending["id"],))
        )
        assert stored["state"] == "superseded"


async def test_omitted_source_disappears_from_pending_badge_and_browser(store):
    memory = Memories(store)
    conversation, receipt, snapshot = await source(store)
    pending = await memory.propose(
        "alice",
        "Pending",
        "Do not retain this source",
        [receipt["messageId"]],
        expected_sources={snapshot["id"]: snapshot["sha256"]},
        conversation_id=conversation["id"],
    )
    saved = await memory.save("alice", "Saved", "Same source", receipt["messageId"])
    await store.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions VALUES(?,?,?,?,?)",
            ("alice", receipt["messageId"], saved["id"], "forgotten_memory", 1),
        ),
        write=True,
    )
    assert (await memory.catalog.list("alice", state="review"))["total"] == 0
    assert (await memory.catalog.facets("alice"))["reviewCount"] == 0
    with pytest.raises(DomainError, match="MEMORY_SOURCE_NOT_FOUND"):
        await memory.details.get("alice", pending["id"])
