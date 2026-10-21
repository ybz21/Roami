"""Main must not turn rejected or unresolved work into a fresh assignment."""

import json

import pytest
from test_routing_policy import request, setup
from test_runtime import ConversationModel
from test_task_delivery_benchmark import admit, mark

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row


async def active_turn(store, binding):
    return await store.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )


def call(key, name, arguments):
    if name in {"delegate", "task_steer"}:
        arguments = {"requestComplete": False, **arguments}
    return {"id": key, "function": {"name": name, "arguments": json.dumps(arguments)}}


@pytest.mark.parametrize("installed", [True, False])
async def test_executor_conflict_cannot_be_silently_removed_after_rejection(store, installed):
    runtime, targets, _, tools, binding = await setup(store, user="Use Claude Code")
    targets.project_default = "codex"
    targets.installed = {"codex", "claude"} if installed else {"codex"}
    runtime.gateway.tools = tools
    try:
        turn = await active_turn(store, binding)
        args = request()
        args.update(executor="claude", target={"kind": "project", "projectId": "p"})
        rejected = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("conflict", "delegate", args), "main", binding
        )
        assert rejected["error"] == "ROUTING_EXECUTOR_CONFLICT"
        args.pop("executor")
        binding["toolCallId"] = "fallback"
        fallback = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("fallback", "delegate", args), "main", binding
        )
        assert fallback["error"] == "ROUTING_EXECUTOR_CONFLICT"
        assert not await runtime.tasks.list("alice")
        args["routing"].update(explicitExecutor="claude", userQuote="Use Claude Code")
        binding["toolCallId"] = "corrected"
        corrected = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call("corrected", "delegate", args),
            "main",
            binding,
        )
        if installed:
            assert corrected["executor"] == "claude"
            assert len(await runtime.tasks.list("alice")) == 1
        else:
            assert corrected["error"] == "ROUTING_EXPLICIT_UNAVAILABLE"
            assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


@pytest.mark.parametrize("operation", ["session_send", "delegate"])
async def test_unknown_run_cannot_be_assigned_to_an_unbound_session_or_replaced(store, operation):
    runtime, targets, _, tools, binding = await setup(store)
    runtime.gateway.tools = tools
    try:
        task = await admit(
            runtime,
            binding,
            "Original work",
            "seed",
            executor="codex",
            target={"kind": "project", "projectId": "p"},
        )
        await mark(runtime, task, "interrupted", {"state": "failed", "outcomeKnown": False})
        turn = await active_turn(store, binding)
        status = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("status", "task_status", {}), "main", binding
        )
        assert status[0]["latestAttempt"]["outcomeKnown"] is False
        args = (
            {"sessionId": "guessed", "text": "Report current progress"}
            if operation == "session_send"
            else {
                **request(),
                "goal": "Report current progress",
                "target": {"kind": "session", "sessionId": "guessed"},
            }
        )
        rejected = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("guess", operation, args), "main", binding
        )
        assert rejected["error"] == "TASK_SESSION_BINDING_REQUIRED"
        assert targets.sends == []
        binding["toolCallId"] = "replacement"
        replacement = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call("replace", "delegate", request()),
            "main",
            binding,
        )
        assert replacement["error"] == "TASK_OUTCOME_UNRESOLVED"
        assert len(await runtime.tasks.list("alice")) == 1
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET session_id='actual' WHERE task_id=?", (task["id"],)
            ),
            write=True,
        )
        await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("refresh", "task_status", {}), "main", binding
        )
        bound = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call(
                "bound", "session_send", {"sessionId": "actual", "text": "Report current progress"}
            ),
            "main",
            binding,
        )
        assert bound["sessionId"] == "actual"
        assert len(targets.sends) == 1
    finally:
        await runtime.close()


async def test_automatic_executor_quote_mismatch_can_be_corrected_without_a_user_choice(store):
    runtime, targets, _, tools, binding = await setup(store)
    targets.project_default = "codex"
    runtime.gateway.tools = tools
    try:
        turn = await active_turn(store, binding)
        args = request(userQuote="Please investigate")
        args["target"] = {"kind": "project", "projectId": "p"}
        rejected = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("quote", "delegate", args), "main", binding
        )
        assert rejected["error"] == "ROUTING_EXECUTOR_INTENT_REQUIRED"
        assert "omit routing.userQuote" in rejected["recovery"]
        assert not await runtime.tasks.list("alice")
        args["routing"].pop("userQuote")
        binding["toolCallId"] = "corrected"
        corrected = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call("corrected", "delegate", args),
            "main",
            binding,
        )
        assert corrected["acceptedOnly"] is True
        assert corrected["executor"] == "codex"
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


async def test_missing_executor_field_reports_its_path_and_accepts_a_corrected_request(store):
    runtime, _, _, tools, binding = await setup(store)
    runtime.gateway.tools = tools
    try:
        turn = await active_turn(store, binding)
        args = request()
        args["routing"].pop("explicitExecutor")
        rejected = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("missing", "delegate", args), "main", binding
        )
        assert rejected["error"] == "INVALID_TOOL_ARGUMENTS"
        assert rejected["missingFields"] == ["routing.explicitExecutor"]
        assert rejected["recovery"].startswith("Missing required fields: routing.explicitExecutor.")
        assert not await runtime.tasks.list("alice")
        args["routing"]["explicitExecutor"] = None
        binding["toolCallId"] = "corrected"
        corrected = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call("corrected", "delegate", args),
            "main",
            binding,
        )
        assert corrected["acceptedOnly"] is True
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "fallback",
    [
        {"kind": "new_session"},
        {"kind": "new_session", "resourceOnly": True},
        {"kind": "project", "projectId": "other"},
    ],
)
async def test_rejected_destination_cannot_be_removed_or_replaced_until_a_new_user_turn(
    store, tmp_path, fallback
):
    runtime, _, _, _, binding = await setup(store)
    try:
        turn = await store.call(
            lambda db: row(
                db,
                "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
                (binding["turnId"],),
            )
        )
        first = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call(
                "bad-path",
                "delegate",
                {
                    "goal": "Save report",
                    "target": {"kind": "new_session", "directory": str(tmp_path / "missing")},
                },
            ),
            "main",
            binding,
        )
        assert first["error"] == "EXECUTION_DIRECTORY_UNAVAILABLE"
        second = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call(
                "bypass-path",
                "delegate",
                {"goal": "Save the report with different wording", "target": fallback},
            ),
            "main",
            binding,
        )
        assert second["error"] == "TASK_TARGET_REVIEW_REQUIRED"
        assert not await runtime.tasks.list("alice")
        await store.call(
            lambda db: db.execute("UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)),
            write=True,
        )
        receipt = await runtime.conversations.accept(
            "alice", binding["conversation"], "correction", "Use this actual directory"
        )
        job = await store.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (receipt["turnId"],))
        )
        new_turn = await runtime.mailbox.claim(job)
        mid = await runtime.journal.start(new_turn)
        corrected = await runtime.gateway.invoke(
            new_turn,
            mid,
            call(
                "corrected",
                "delegate",
                {
                    "goal": "Save report",
                    "target": {"kind": "new_session", "directory": str(tmp_path)},
                },
            ),
            "main",
            {**binding, "turnId": new_turn["id"], "originMessageId": receipt["messageId"]},
        )
        assert corrected["acceptedOnly"] is True
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


async def test_unknown_continuation_returns_immediate_block_without_accepting_or_polling(store):
    class Main:
        model = "continuation-handoff"
        task_id = None
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 2:
                assert json.loads(messages[-1]["content"])["error"] == "TASK_OUTCOME_UNRESOLVED"
                yield ModelEvent(
                    "text", "The previous execution is unconfirmed; continuation is blocked."
                )
                return
            assert self.calls == 1, (
                "Main must not poll or redelegate after the blocked continuation"
            )
            yield ModelEvent(
                "tool",
                call(
                    "continue",
                    "bash",
                    {
                        "argv": [
                            "roami",
                            "agent",
                            "capability",
                            "call",
                            "task_steer",
                            "--input",
                            json.dumps(
                                {
                                    "taskId": self.task_id,
                                    "revision": 1,
                                    "text": "Continue after the old execution is confirmed stopped",
                                    "requestComplete": False,
                                }
                            ),
                        ]
                    },
                ),
            )

    model = Main()
    runtime = Runtime(store, model, memory_model=ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            c["id"],
            "Original work",
            key="original",
            executor="codex",
            target={"kind": "project", "projectId": "p"},
            record_intent=True,
        )
        model.task_id = task["id"]
        await mark(
            runtime,
            task,
            "interrupted",
            {
                "state": "failed",
                "summary": "EXECUTION_DEADLINE_OR_INTERRUPTION",
                "outcomeKnown": False,
            },
        )
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "next", "Continue only after confirming the previous run stopped"
        )
        job = await store.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (receipt["turnId"],))
        )
        turn = await runtime.mailbox.claim(job)
        await runtime.loop.run(turn, "main")
        assert model.calls == 2
        await runtime.tasks.revisions.advance()
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["task"]["revision"] == 1
        assert detail["task"]["latestAttempt"]["outcomeKnown"] is False
        assert detail["task"]["latestAttempt"]["stopConfirmed"] is False
        assert detail["steering"] is None
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


async def test_accepted_steering_cannot_be_replaced_with_another_task_in_the_same_scope(store):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(
            runtime,
            binding,
            "Original work",
            "original",
            executor="codex",
            target={"kind": "project", "projectId": "p"},
        )
        await mark(runtime, task)
        turn = await store.call(
            lambda db: row(
                db,
                "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
                (binding["turnId"],),
            )
        )
        accepted = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call(
                "steer",
                "task_steer",
                {"taskId": task["id"], "revision": 1, "text": "Continue current progress"},
            ),
            "main",
            binding,
        )
        assert accepted["acceptedOnly"] is True
        replacement = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call(
                "replace",
                "delegate",
                {
                    "goal": "Rephrase the continued task",
                    "target": {"kind": "project", "projectId": "p"},
                },
            ),
            "main",
            binding,
        )
        assert replacement["error"] == "TASK_CONTINUATION_ALREADY_REQUESTED"
        independent = await admit(
            runtime,
            binding,
            "Independent work elsewhere",
            "independent",
            target={"kind": "project", "projectId": "other"},
        )
        assert independent["id"] != task["id"]
        assert len(await runtime.tasks.list("alice")) == 2
    finally:
        await runtime.close()
