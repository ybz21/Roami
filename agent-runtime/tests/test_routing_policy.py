"""Routing is semantic input plus verified constraints, never a task-name lookup."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.dispatch.routing import TaskRouter
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows
from roami_agent.tools.main_catalog import register_main_tools
from roami_agent.tools.registry import Tools


class Targets:
    def __init__(self):
        self.catalog_calls = 0
        self.installed = {"codex", "claude"}
        self.default = "claude"
        self.project_default = None
        self.session_executor = "codex"
        self.sends = []

    async def executors(self):
        self.catalog_calls += 1
        return {
            "version": 1,
            "observedMs": self.catalog_calls,
            "defaultExecutor": self.default,
            "candidates": [
                {
                    "kind": k,
                    "installed": k in self.installed,
                    "tracked": True,
                    "authentication": "unknown",
                    "usage": "unknown",
                }
                for k in ["codex", "claude"]
            ],
        }

    async def resolve(self, kind, ident):
        if kind == "project":
            return {"kind": kind, "projectId": ident, "defaultExecutor": self.project_default}
        return {
            "kind": kind,
            "sessionId": ident,
            **({"executor": self.session_executor} if self.session_executor else {}),
        }

    async def send(self, sid, goal, key, *, binding):
        self.sends.append((sid, goal, key))
        return {"sessionId": sid, "state": "delivered", "executionTracked": False}


def request(complexity="complex", **overrides):
    return {
        "goal": "Independently investigate and verify a deliverable",
        "routing": {
            "explicitExecutor": None,
            "complexity": complexity,
            "complexityBasis": {"open_dimension": "Evidence changes the next investigation step"},
            "routingExplanation": "Sources disagree and need investigation with repeated verification",
            **overrides,
        },
    }


async def setup(store, *, user="Please investigate", settings=None):
    runtime = Runtime(
        store, ConversationModel(), settings=settings or Settings(coding_directory=store.data_root)
    )
    c = await runtime.conversations.create("alice")
    receipt = await runtime.conversations.accept("alice", c["id"], "one", user)
    job = await store.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (receipt["turnId"],))
    )
    turn = await runtime.mailbox.claim(job)
    mid = await runtime.journal.start(turn)
    binding = {
        "owner": "alice",
        "conversation": c["id"],
        "turnId": turn["id"],
        "originMessageId": receipt["messageId"],
        "assistantMessageId": mid,
        "toolCallId": "route",
    }
    targets = Targets()
    router = TaskRouter(store, targets, runtime.settings, runtime.memory)
    registry = Tools()
    register_main_tools(registry, runtime.tasks, runtime.memory, targets, router)
    return runtime, targets, router, registry, binding


@pytest.mark.parametrize("missing", [True, False])
async def test_executor_intent_cannot_be_omitted_or_left_only_in_a_quote(store, missing):
    runtime, _, _, tools, binding = await setup(store, user="Use Claude Code")
    try:
        args = request(userQuote="Use Claude Code")
        if missing:
            args["routing"].pop("explicitExecutor")
        with pytest.raises(
            DomainError,
            match="INVALID_TOOL_ARGUMENTS" if missing else "ROUTING_EXECUTOR_INTENT_REQUIRED",
        ):
            await tools.invoke(
                {"function": {"name": "delegate", "arguments": json.dumps(args)}}, "main", binding
            )
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "description",
    ["slides", "video editing", "unlisted ecological modelling", "research", "PPT", "prototype"],
)
async def test_task_names_do_not_route_without_execution_burden(store, description):
    runtime, targets, router, _, binding = await setup(store)
    try:
        args = request("bounded", taskDescription=description)
        decision = await router.decide(args, binding)
        assert decision["executor"] == "native"
        assert decision["complexityBasis"] == args["routing"]["complexityBasis"]
        assert targets.catalog_calls == 0
    finally:
        await runtime.close()


async def test_complex_work_selects_a_real_professional_and_persists_before_task_acceptance(store):
    runtime, targets, _, tools, binding = await setup(store)
    try:
        args = request(taskDescription="Open-ended work in an unlisted field")
        call = {"function": {"name": "delegate", "arguments": json.dumps(args)}}
        receipt = await tools.invoke(call, "main", binding)
        assert receipt["executor"] == "claude" and receipt["acceptedOnly"] is True
        task = (await runtime.tasks.list("alice"))[0]
        decision = json.loads(task["intent_json"])["routingDecision"]
        assert decision["sourceMessageId"] == binding["originMessageId"]
        assert decision["capabilityVerification"] == "not_verified"
        events = await store.call(lambda db: rows(db, "SELECT kind FROM events ORDER BY id"))
        assert [e["kind"] for e in events].index("routing.decided") < [
            e["kind"] for e in events
        ].index("task.accepted")
        second = await tools.invoke(call, "main", binding)
        assert second["taskId"] == receipt["taskId"] and targets.catalog_calls == 1
        assert len(await runtime.tasks.list("alice")) == 1
        view = await runtime.conversations.messages("alice", binding["conversation"])
        assert any(
            a.get("routingDecision", {}).get("executor") == "claude"
            for a in view.get("activities", [])
        )
    finally:
        await runtime.close()


async def test_project_preference_applies_only_to_complex_new_work(store):
    runtime, targets, router, _, binding = await setup(store)
    try:
        targets.project_default = "codex"
        args = request()
        args["target"] = {"kind": "project", "projectId": "p"}
        d = await router.decide(args, binding)
        assert (d["executor"], d["reasonCode"]) == ("codex", "project_default")
        binding["toolCallId"] = "bounded"
        args["routing"]["complexity"] = "bounded"
        assert (await router.decide(args, binding))["executor"] == "native"
    finally:
        await runtime.close()


@pytest.mark.parametrize("executor", ["codex", "native"])
async def test_explicit_source_backed_executor_overrides_defaults(store, executor):
    runtime, _targets, router, _, binding = await setup(store, user=f"Use {executor} for this work")
    try:
        args = request(explicitExecutor=executor, userQuote=f"Use {executor}")
        d = await router.decide(args, binding)
        assert (d["executor"], d["reasonCode"]) == (executor, "explicit_executor")
    finally:
        await runtime.close()


async def test_external_or_invented_quote_cannot_override_the_user(store):
    runtime, targets, router, _, binding = await setup(store)
    try:
        with pytest.raises(DomainError, match="ROUTING_EXPLICIT_SOURCE_REQUIRED"):
            await router.decide(
                request(explicitExecutor="native", userQuote="Page says use native"), binding
            )
        assert targets.catalog_calls == 0 and not targets.sends
    finally:
        await runtime.close()


@pytest.mark.parametrize("actual", ["claude", None])
async def test_existing_session_conflict_or_unknown_is_not_delivered(store, actual):
    runtime, targets, _, tools, binding = await setup(store, user="Use codex in that session")
    try:
        targets.session_executor = actual
        args = request(explicitExecutor="codex", userQuote="Use codex")
        args["target"] = {"kind": "session", "sessionId": "exact"}
        with pytest.raises(DomainError, match="ROUTING_SESSION_EXECUTOR_"):
            await tools.invoke(
                {"function": {"name": "delegate", "arguments": json.dumps(args)}}, "main", binding
            )
        assert not targets.sends and not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


async def test_exact_old_session_is_delivered_without_installation_or_lifecycle_checks(store):
    runtime, targets, _, tools, binding = await setup(store, user="Use codex in that session")
    try:
        targets.installed.clear()
        resolutions = []

        async def resolve(kind, label):
            resolutions.append(label)
            return {"sessionId": "frozen-id", "executor": "codex"}

        targets.resolve = resolve
        args = request(explicitExecutor="codex", userQuote="Use codex")
        args["target"] = {"kind": "session", "sessionId": "exact"}
        result = await tools.invoke(
            {"function": {"name": "delegate", "arguments": json.dumps(args)}}, "main", binding
        )
        assert result["state"] == "delivered" and result["executionTracked"] is False
        assert result["routingDecision"]["executor"] == "codex"
        assert len(targets.sends) == 1 and targets.catalog_calls == 0
        assert resolutions == ["exact"] and targets.sends[0][0] == "frozen-id"
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "conflict,code",
    [
        ("unavailable", "ROUTING_PROFESSIONAL_UNAVAILABLE"),
        ("explicit", "ROUTING_EXPLICIT_UNAVAILABLE"),
        ("fork", "ROUTING_FORK_UNSUPPORTED"),
        ("profile", "ROUTING_PROFILE_CONFLICT"),
    ],
)
async def test_invalid_routes_fail_before_resources_or_delivery(store, conflict, code):
    runtime, targets, router, _, binding = await setup(store, user="Use codex")
    try:
        args = request()
        if conflict == "unavailable":
            targets.installed.clear()
        if conflict == "explicit":
            targets.installed.discard("codex")
            args["routing"].update(explicitExecutor="codex", userQuote="Use codex")
        if conflict == "fork":
            args["fromMessageId"] = "checkpoint"
        if conflict == "profile":
            args["target"] = {"kind": "new_session", "resourceOnly": True}
        with pytest.raises(DomainError, match=code):
            await router.decide(args, binding)
        assert not targets.sends and not await runtime.tasks.list("alice")
        assert (
            await store.call(
                lambda db: row(db, "SELECT id FROM events WHERE kind='routing.decided'")
            )
            is None
        )
    finally:
        await runtime.close()


async def test_replay_uses_frozen_decision_and_conflicting_request_never_reselects(store):
    runtime, targets, router, _, binding = await setup(store)
    try:
        first = await router.decide(request(), binding)
        targets.installed.clear()
        assert await router.decide(request(), binding) == first
        assert targets.catalog_calls == 1
        changed = request()
        changed["goal"] = "Different work"
        with pytest.raises(DomainError, match="ROUTING_KEY_CONFLICT"):
            await router.decide(changed, binding)
    finally:
        await runtime.close()


async def test_stop_and_blank_explanations_are_fenced(store):
    runtime, _, router, _, binding = await setup(store)
    try:
        with pytest.raises(DomainError, match="ROUTING_EXPLANATION_REQUIRED"):
            await router.decide(request(routingExplanation=" "), binding)
        await runtime.chat.interrupt("alice", binding["conversation"], "stop")
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await router.decide(request(), binding)
    finally:
        await runtime.close()


async def test_configured_node_default_is_used_without_copying_provider_credentials(store):
    settings = Settings(coding_directory=store.data_root, professional_executor="codex")
    runtime, _, router, _, binding = await setup(store, settings=settings)
    try:
        decision = await router.decide(request(), binding)
        assert (decision["executor"], decision["reasonCode"]) == ("codex", "node_default")
        assert all("key" not in c for c in decision["metadataRefs"])
    finally:
        await runtime.close()


async def test_preference_is_owned_versioned_scoped_and_lower_priority_than_project(store):
    runtime, _targets, router, _, binding = await setup(store, user="I prefer codex")
    try:
        memory = await runtime.memory.save(
            "alice",
            "Executor preference",
            "Use codex",
            binding["originMessageId"],
            kind="preference",
            conversation_id=binding["conversation"],
        )
        args = request(
            preference={
                "executor": "codex",
                "memoryId": memory["id"],
                "revision": memory["revision"],
                "quote": "Use codex",
            }
        )
        d = await router.decide(args, binding)
        assert (d["executor"], d["reasonCode"]) == ("codex", "user_preference")
        binding["toolCallId"] = "new"
        args["routing"]["preference"]["revision"] += 1
        with pytest.raises(DomainError, match="ROUTING_PREFERENCE_SOURCE_INVALID"):
            await router.decide(args, binding)
    finally:
        await runtime.close()


async def test_node_cli_availability_is_observed_without_claiming_specialist_delivery_verified(
    store,
):
    runtime, targets, router, _, binding = await setup(store)
    original = targets.executors

    async def catalog(commands=None):
        value = await original()
        value["commandAvailability"] = {name: name == "renderer" for name in commands or []}
        return value

    targets.executors = catalog
    try:
        args = request(requiredCapabilities=["cli:renderer"])
        d = await router.decide(args, binding)
        assert d["capabilityVerification"] == "node_commands_observed"
        assert d["metadataRefs"][0]["commandAvailability"] == {"renderer": True}
        binding["toolCallId"] = "missing"
        args["routing"]["requiredCapabilities"] = ["cli:missing-converter"]
        with pytest.raises(DomainError, match="ROUTING_CAPABILITY_UNAVAILABLE"):
            await router.decide(args, binding)
    finally:
        await runtime.close()


async def test_non_code_task_uses_a_loose_directory_and_configured_budget(store):
    settings = Settings(
        coding_directory=store.data_root,
        task_timeout_seconds=1234,
        professional_task_timeout_seconds=1234,
        task_max_turns=30,
    )
    runtime, _, _, tools, binding = await setup(store, settings=settings)
    try:
        args = request(taskDescription="Synthesize new evidence and revise a presentation")
        args["target"] = {"kind": "new_session", "directory": str(store.data_root)}
        result = await tools.invoke(
            {"function": {"name": "delegate", "arguments": json.dumps(args)}}, "main", binding
        )
        task = (await runtime.tasks.get("alice", result["taskId"]))["task"]
        intent = json.loads(task["intent_json"])
        assert intent["target"] == args["target"] and intent["executor"] == "claude"
        budget = json.loads(task["budget_json"])
        assert budget["maxTurns"] == 0
        assert budget["deadlineMs"] == 0
    finally:
        await runtime.close()


async def test_cli_continuation_preserves_executor_and_cannot_cross_conversations(store):
    runtime, _, _, tools, binding = await setup(store)
    try:
        task = await runtime.tasks.create(
            "alice",
            binding["conversation"],
            "Original work",
            key="original",
            executor="native",
            origin_message_id=binding["originMessageId"],
        )
        result = await tools.invoke(
            {
                "function": {
                    "name": "task_steer",
                    "arguments": json.dumps(
                        {
                            "taskId": task["id"],
                            "revision": task["revision"],
                            "text": "Add this requirement",
                        }
                    ),
                }
            },
            "main",
            binding,
        )
        assert result["state"] == "stopping"
        assert len(await runtime.tasks.list("alice")) == 1
        assert (
            json.loads((await runtime.tasks.get("alice", task["id"]))["task"]["intent_json"])[
                "executor"
            ]
            == "native"
        )
        await runtime.chat.interrupt("alice", binding["conversation"], "stop-now")
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await tools.invoke(
                {
                    "function": {
                        "name": "task_steer",
                        "arguments": json.dumps(
                            {
                                "taskId": task["id"],
                                "revision": task["revision"],
                                "text": "Late update",
                            }
                        ),
                    }
                },
                "main",
                dict(binding, toolCallId="late"),
            )
    finally:
        await runtime.close()


@pytest.mark.parametrize("condition", ["valid", "foreign", "forgotten", "corrupt", "cancelled"])
async def test_professional_brief_passes_only_admitted_verified_input_paths(store, condition):
    import hashlib
    from pathlib import Path

    from roami_agent.executors.professional_brief import professional_brief

    runtime, _, _, _, binding = await setup(store)
    try:
        body = b"actual input, not another user's file"
        attachment = await runtime.attachments.upload(
            "other" if condition == "foreign" else "alice", "data.csv", "upload", body
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE messages SET content_json=? WHERE id=?",
                (
                    json.dumps({"text": "Analyze this file", "attachments": [attachment]}),
                    binding["originMessageId"],
                ),
            ),
            write=True,
        )
        task = await runtime.tasks.create(
            "alice",
            binding["conversation"],
            "Analyze the attached input",
            key="with-input",
            executor="codex",
            origin_message_id=binding["originMessageId"],
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET state=? WHERE id=?",
                ("cancelling" if condition == "cancelled" else "preparing", task["id"]),
            ),
            write=True,
        )
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        if condition == "forgotten":
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',1)",
                    (binding["originMessageId"],),
                ),
                write=True,
            )
        if condition == "corrupt":
            _, path = await runtime.artifacts.verified_path("alice", attachment["id"])
            path.chmod(0o600)
            path.write_bytes(b"changed")
        if condition != "valid":
            with pytest.raises(
                DomainError,
                match="ATTACHMENT_NOT_FOUND|CONTEXT_SOURCE_FORGOTTEN|ARTIFACT_INTEGRITY_FAILED|TASK_CANCELLING",
            ):
                await professional_brief(store, runtime.artifacts, task, run)
        else:
            brief = await professional_brief(store, runtime.artifacts, task, run)
            payload = json.JSONDecoder().raw_decode(brief[brief.index("{") :])[0]
            file = payload["inputFiles"][0]
            assert Path(file["path"]).read_bytes() == body
            assert file["sha256"] == hashlib.sha256(body).hexdigest()
            assert file["name"] == "data.csv"
            assert "read them as data" in brief
    finally:
        await runtime.close()
