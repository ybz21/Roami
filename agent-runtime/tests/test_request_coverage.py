"""A direct answer cannot erase the independent repair requested alongside it."""

import json

import pytest
from test_coordinator_handoff import call
from test_main_intent_scheduling import completed
from test_routing_policy import setup
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import rows
from roami_agent.storage.request_coverage import latest_coverage

REPORT = "把报告用 Markdown 给我"
REPAIR = "并在 Roami 建任务修复报告链接"
USER = REPORT + "，" + REPAIR


def inventory(first="answered", second="pending", **fields):
    return [
        {"quote": REPORT, "status": first},
        {"quote": REPAIR, "status": second, **fields},
    ]


@pytest.mark.parametrize(
    "outcomes,code",
    [
        (inventory(), "REQUEST_OUTCOMES_PENDING"),
        (inventory(second="delegated", taskId="invented"), "REQUEST_HANDOFF_REQUIRED"),
        (inventory(second="current"), "REQUEST_HANDOFF_REQUIRED"),
        (inventory(second="blocked"), "REQUEST_BLOCKER_REQUIRED"),
        ([{"quote": "invented", "status": "answered"}], "REQUEST_COVERAGE_SOURCE_REQUIRED"),
    ],
)
async def test_reply_rejects_pending_or_fabricated_dispositions(store, outcomes, code):
    runtime, _, _, registry, binding = await setup(store, user=USER)
    try:
        with pytest.raises(DomainError, match=code):
            await registry.invoke(
                call("reply", {"text": "已记录，等你开工。", "requestCoverage": outcomes}),
                "main",
                binding,
            )
        assert not await store.call(lambda db: latest_coverage(db, binding["turnId"]))
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "second,error",
    [
        ("pending", "REQUEST_OUTCOMES_PENDING"),
        ("current", "REQUEST_HANDOFF_SCOPE_REQUIRED"),
    ],
)
async def test_final_handoff_rejects_other_pending_outcomes_before_creating_task(
    store, second, error
):
    runtime, _, _, registry, binding = await setup(store, user=USER)
    try:
        with pytest.raises(DomainError, match=error):
            await registry.invoke(
                call(
                    "delegate",
                    {
                        "goal": "Convert the report",
                        "requestComplete": True,
                        "requestCoverage": inventory(first="current", second=second),
                    },
                ),
                "main",
                binding,
            )
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


async def test_steering_cannot_send_independent_outcome_in_source_quote(store):
    runtime, _, _, registry, binding = await setup(store, user=USER)
    try:
        with pytest.raises(DomainError, match="REQUEST_HANDOFF_SCOPE_REQUIRED"):
            await registry.invoke(
                call(
                    "task_steer",
                    {
                        "taskId": "not-yet-looked-up",
                        "revision": 1,
                        "text": USER,
                        "sourceQuote": USER,
                        "requestComplete": False,
                        "requestCoverage": inventory(first="current"),
                    },
                ),
                "main",
                binding,
            )
        assert not await store.call(
            lambda db: rows(db, "SELECT * FROM jobs WHERE kind='task.steer'")
        )
    finally:
        await runtime.close()


async def test_persisted_inventory_cannot_drop_second_outcome_or_omit_inventory(store):
    runtime, _, _, registry, binding = await setup(store, user=USER)
    try:
        await registry.invoke(
            call(
                "delegate",
                {
                    "goal": "Convert report",
                    "requestComplete": False,
                    "requestCoverage": inventory(first="current"),
                },
            ),
            "main",
            binding,
        )
        for args, error in [
            ({"text": "已记录。"}, "REQUEST_COVERAGE_REQUIRED"),
            (
                {
                    "text": "已给报告。",
                    "requestCoverage": [{"quote": REPORT, "status": "answered"}],
                },
                "REQUEST_OUTCOME_DROPPED",
            ),
        ]:
            with pytest.raises(DomainError, match=error):
                await registry.invoke(call("reply", args), "main", binding)
        with pytest.raises(DomainError, match="REQUEST_COVERAGE_REQUIRED"):
            await registry.invoke(call("task_queue_reply", {}), "main", binding)
        _plan, prompt = await runtime.loop.context.build(
            await store.call(
                lambda db: dict(
                    db.execute("SELECT * FROM turns WHERE id=?", (binding["turnId"],)).fetchone(),
                    owner_id="alice",
                )
            ),
            runtime.settings.main_instructions,
            registry.catalog(),
            None,
        )
        assert any(
            "Persisted outcome inventory" in m["content"] and REPAIR in m["content"] for m in prompt
        )
    finally:
        await runtime.close()


async def test_report_and_framework_repair_are_both_handed_off_without_polling(store):
    rounds = 0
    first_id = None

    class Main:
        model = "report-and-repair"

        async def stream(self, messages, tools):
            nonlocal rounds, first_id
            rounds += 1
            if rounds == 1:
                yield ModelEvent(
                    "tool",
                    call(
                        "delegate",
                        {
                            "goal": "把现有报告转为 Markdown，保留原数据。",
                            "requestComplete": False,
                            "requestCoverage": inventory(first="current"),
                        },
                        "report",
                    ),
                )
            else:
                assert rounds == 2
                first_id = json.loads(messages[-1]["content"])["taskId"]
                yield ModelEvent(
                    "tool",
                    call(
                        "delegate",
                        {
                            "goal": "修复 Roami 报告链接与 Markdown 交付。",
                            "requestComplete": True,
                            "requestCoverage": [
                                {"quote": REPORT, "status": "delegated", "taskId": first_id},
                                {"quote": REPAIR, "status": "current"},
                            ],
                        },
                        "repair",
                    ),
                )

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        submitted = await runtime.chat.submit("alice", conversation["id"], "both", USER)
        await completed(store, submitted["turnId"])
        tasks = await runtime.tasks.list("alice", conversation["id"])
        assert len(tasks) == 2 and rounds == 2
        outcomes = await store.call(lambda db: latest_coverage(db, submitted["turnId"]))
        assert {item["taskId"] for item in outcomes} == {t["id"] for t in tasks}
        assert all(item["status"] == "delegated" for item in outcomes)
        assert not await store.call(
            lambda db: rows(db, "SELECT * FROM tool_calls WHERE tool_name='task_status'")
        )
    finally:
        await runtime.close()


async def test_direct_report_is_delivered_after_independent_repair_acceptance(store):
    rounds = 0

    class Main:
        model = "direct-report-and-repair"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                yield ModelEvent(
                    "tool",
                    call(
                        "delegate",
                        {
                            "goal": "修复 Roami 报告链接",
                            "requestComplete": False,
                            "requestCoverage": inventory(first="pending", second="current"),
                        },
                    ),
                )
            else:
                assert rounds == 2
                task_id = json.loads(messages[-1]["content"])["taskId"]
                yield ModelEvent(
                    "tool",
                    call(
                        "reply",
                        {
                            "text": "报告：首屏资源减少 7.6%。链接修复任务已排队。",
                            "requestCoverage": inventory(second="delegated", taskId=task_id),
                        },
                    ),
                )

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        accepted = await runtime.chat.submit("alice", c["id"], "direct", USER)
        await completed(store, accepted["turnId"])
        assert len(await runtime.tasks.list("alice", c["id"])) == 1
        history = await runtime.conversations.messages("alice", c["id"])
        assert (
            history["messages"][-1]["content"]["text"]
            == "报告：首屏资源减少 7.6%。链接修复任务已排队。"
        )
        assert rounds == 2
    finally:
        await runtime.close()


async def test_completion_callback_does_not_reinvent_original_request_inventory(store):
    class Main:
        model = "completion-with-inventory"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "tool",
                call(
                    "reply",
                    {
                        "text": "Completed the requested task.",
                        "requestCoverage": [
                            {"quote": "Original user request", "status": "answered"}
                        ],
                    },
                ),
            )

    runtime = Runtime(
        store, Main(), worker_model=ConversationModel(), memory_model=ConversationModel()
    )
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        await runtime.tasks.create(
            "alice", c["id"], "Original user request", key="completion", record_intent=True
        )
        await until(
            store,
            lambda db: db.execute(
                "SELECT 1 FROM turns WHERE trigger_kind='completion' AND state='completed'"
            ).fetchone(),
        )
        history = await runtime.conversations.messages("alice", c["id"])
        assert history["messages"][-1]["content"]["text"] == "Completed the requested task."
    finally:
        await runtime.close()
