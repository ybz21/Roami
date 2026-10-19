import httpx
from test_memory_pipeline import source
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.memory.records import Memories
from roami_agent.protocol.identity import now_ms
from roami_agent.server.http import create_app


async def test_catalog_browses_scoped_and_personal_records_without_changing_recall(store):
    memory = Memories(store)
    c1, r1, _ = await source(store)
    c2, r2, snapshot = await source(store, text="项目使用 Python")
    _, other, _ = await source(store, owner="bob")
    local = await memory.save(
        "alice", "语言", "简短中文", r1["messageId"], conversation_id=c1["id"]
    )
    personal = await memory.save(
        "alice", "个人偏好", "简短中文", r1["messageId"], kind="preference"
    )
    project = await memory.save(
        "alice",
        "技术栈",
        "Python",
        r2["messageId"],
        conversation_id=c2["id"],
        project_id="project-a",
    )
    await memory.save("bob", "Private", "Secret", other["messageId"])
    result = await memory.catalog.list("alice")
    assert result["total"] == 3
    assert {item["id"] for item in result["items"]} == {local["id"], personal["id"], project["id"]}
    assert all(item["source_count"] == 1 for item in result["items"])
    evidence = (await memory.evidence("alice", personal["id"]))[0]
    assert evidence["conversationId"] == c1["id"]
    assert evidence["branchId"] == c1["active_branch_id"]
    assert evidence["messageId"] == r1["messageId"]
    assert (await memory.catalog.list("alice", personal_only=True))["items"][0]["id"] == personal[
        "id"
    ]
    assert (await memory.catalog.list("alice", project_id="project-a"))["items"][0][
        "id"
    ] == project["id"]
    assert (await memory.catalog.list("alice", conversation_id=c1["id"]))["total"] == 1
    assert (await memory.catalog.list("alice", kind="preference"))["total"] == 1
    assert await memory.search("alice", "Python", conversation_id=c1["id"]) == []
    await memory.propose(
        "alice",
        "待确认",
        "事实",
        [r2["messageId"]],
        expected_sources={snapshot["id"]: snapshot["sha256"]},
        conversation_id=c2["id"],
    )
    assert (await memory.catalog.list("alice", state="candidate"))["total"] == 1
    await memory.delete("alice", local["id"])
    assert (await memory.catalog.list("alice"))["total"] == 2
    await store.call(
        lambda db: db.execute(
            "UPDATE memory_records SET expires_ms=? WHERE id=?", (now_ms() - 1, project["id"])
        ),
        write=True,
    )
    assert (await memory.catalog.list("alice"))["total"] == 1


async def test_catalog_http_pagination_literal_search_and_owner_isolation(store):
    runtime = Runtime(store, ConversationModel())
    conversation, receipt, _ = await source(store)
    for index in range(25):
        await runtime.memory.save(
            "alice",
            f"记忆 {index:02}",
            f"内容 {index:02}",
            receipt["messageId"],
            conversation_id=conversation["id"],
        )
    await runtime.memory.save(
        "alice",
        "100%_literal",
        "精确标点",
        receipt["messageId"],
        conversation_id=conversation["id"],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        first = (await client.get("/v1/memories/catalog")).json()["data"]
        second = (await client.get("/v1/memories/catalog?offset=20")).json()["data"]
        assert first["total"] == second["total"] == 26
        assert len(first["items"]) == 20 and len(second["items"]) == 6
        assert not (
            {item["id"] for item in first["items"]} & {item["id"] for item in second["items"]}
        )
        literal = (await client.get("/v1/memories/catalog", params={"query": "%_"})).json()["data"]
        assert literal["total"] == 1 and literal["items"][0]["title"] == "100%_literal"
        assert (await client.get("/v1/memories/catalog?limit=101")).status_code == 422
        assert (await client.get("/v1/memories/catalog?offset=-1")).status_code == 422
        assert (await client.get("/v1/memories/catalog", headers={"X-Roami-Owner": "bob"})).json()[
            "data"
        ]["total"] == 0
        denied = await client.get(
            "/v1/memories/catalog",
            params={"conversationId": conversation["id"]},
            headers={"X-Roami-Owner": "bob"},
        )
        assert denied.status_code == 404


async def test_catalog_includes_daily_records_without_adding_them_to_normal_recall(store):
    memory = Memories(store)
    conversation, receipt, _ = await source(store)
    daily = await memory.save(
        "alice",
        "每日摘要",
        '{"counts":{"tasksCompleted":2},"scopeKey":"unassigned"}',
        receipt["messageId"],
        kind="summary",
        conversation_id=conversation["id"],
        day_key="2026-10-18",
    )
    assert (await memory.catalog.list("alice"))["items"][0]["id"] == daily["id"]
    assert (await memory.catalog.list("alice", day_key="2026-10-18", timezone="UTC"))["total"] == 1
    assert (await memory.catalog.list("alice", day_key="2026-10-18", timezone="Asia/Shanghai"))[
        "total"
    ] == 0
    assert (await memory.catalog.list("alice", personal_only=True))["total"] == 0
    assert await memory.search("alice", conversation_id=conversation["id"]) == []


async def test_catalog_task_filter_exposes_the_human_readable_goal(store):
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.dispatch.tasks import Tasks

    memory = Memories(store)
    conversation, receipt, _ = await source(store)
    task = await Tasks(store, Conversations(store)).create(
        "alice",
        conversation["id"],
        "检查统一记忆",
        key="memory-task",
        origin_message_id=receipt["messageId"],
    )
    saved = await memory.save(
        "alice",
        "任务结论",
        "已通过",
        receipt["messageId"],
        conversation_id=conversation["id"],
        task_id=task["id"],
        kind="decision",
    )
    result = await memory.catalog.list("alice", task_id=task["id"])
    assert result["total"] == 1
    assert result["items"][0]["id"] == saved["id"]
    assert result["items"][0]["task_title"] == "检查统一记忆"


async def test_catalog_categories_filter_before_counting_pagination_and_http(store):
    memory = Memories(store)
    _, receipt, _ = await source(store)
    facts = []
    for index in range(2):
        facts.append(
            await memory.save("alice", f"Fact {index}", "Remember this", receipt["messageId"])
        )
    daily = []
    for day in ["2026-10-18", "2026-10-17"]:
        daily.append(
            await memory.save(
                "alice",
                "Daily",
                '{"counts":{"userTurns":3}}',
                receipt["messageId"],
                kind="summary",
                day_key=day,
            )
        )
    assert (await memory.catalog.list("alice"))["total"] == 4
    knowledge = await memory.catalog.list("alice", category="knowledge", limit=1, offset=1)
    assert knowledge["total"] == 2 and len(knowledge["items"]) == 1
    assert knowledge["items"][0]["id"] in {item["id"] for item in facts}
    activity = await memory.catalog.list("alice", category="activity")
    assert [item["id"] for item in activity["items"]] == [item["id"] for item in daily]
    assert (await memory.catalog.list("bob", category="knowledge"))["total"] == 0
    runtime = Runtime(store, ConversationModel())
    try:
        transport = httpx.ASGITransport(app=create_app(runtime))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers={"X-Roami-Owner": "alice"}
        ) as client:
            response = await client.get("/v1/memories/catalog?category=knowledge&limit=1")
            assert response.json()["data"]["total"] == 2
            assert (await client.get("/v1/memories/catalog?category=invalid")).status_code == 422
    finally:
        await runtime.close()
