"""The private bridge keeps host model capacity for real runtime compaction."""

import json
from dataclasses import replace

import pytest

from roami_agent.app import Runtime
from roami_agent.context.token_estimate import request_context
from roami_agent.improvement.evaluation.execution import containers
from roami_agent.improvement.evaluation.execution.container_agent import container_settings
from roami_agent.improvement.evaluation.execution.executors import NativeFilesExecutor
from roami_agent.improvement.evaluation.protocol_suite import protocol_suite
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


def configured():
    main = Settings(
        endpoint="https://private.invalid/v1",
        model="private-main",
        key_env="PRIVATE_KEY",
        context_window=24000,
        compaction_ratio=0.6,
        reserve_tokens=1000,
        keep_recent_tokens=3000,
        model_parameters={"reasoning_effort": "low"},
    )
    return replace(
        main,
        worker_route=replace(
            main.route("worker"),
            name="private-worker",
            context_window=48000,
            capabilities={"images": True},
            image_limits={"max_width": 900},
        ),
    )


async def captured_request(settings, root, monkeypatch):
    async def docker(*args, **kwargs):
        if args[0] == "start":
            raise TimeoutError
        return b""

    async def remove(*args):
        pass

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(settings, shared_daily_limit=True)
    executor.image_id = "no-model-fixture"
    monkeypatch.setattr(executor, "remove", remove)
    await executor.run(protocol_suite()["cases"][0], {}, root)
    return json.loads((root / "state/request.json").read_text())


async def test_configured_role_windows_reach_the_container_without_connection_material(
    tmp_path, monkeypatch
):
    host = configured()
    request = await captured_request(host, tmp_path, monkeypatch)
    child = container_settings(request)
    for role in ["main", "worker"]:
        plan = request_context(child, "", [], role)
        assert plan["contextWindow"] == host.route(role).context_window
        assert plan["compactionThreshold"] == host.threshold_for(role)
        assert plan["reserveTokens"] == host.reserve_tokens
        assert plan["compactionRatio"] == host.compaction_ratio
    assert child.keep_recent_tokens == host.keep_recent_tokens
    assert child.route("worker").image_limits == {"max_width": 900}
    assert child.route("worker").capabilities["images"] is True
    assert child.model_retries == 0  # Only the host retries upstream calls.
    wire = json.dumps(request)
    for private in [
        "private.invalid",
        "private-main",
        "private-worker",
        "PRIVATE_KEY",
        "reasoning_effort",
    ]:
        assert private not in wire


@pytest.mark.parametrize(
    "field,value",
    [("compaction_ratio", 0.5), ("reserve_tokens", 2000), ("keep_recent_tokens", 4000)],
)
def test_context_policy_changes_cannot_reuse_the_old_model_fingerprint(field, value):
    host = configured()
    assert (
        NativeFilesExecutor(host).model_hash
        != NativeFilesExecutor(replace(host, **{field: value})).model_hash
    )
    assert (
        containers.ContainerExecutor(host, shared_daily_limit=True).model_hash
        != containers.ContainerExecutor(
            replace(host, **{field: value}), shared_daily_limit=True
        ).model_hash
    )


async def test_unknown_windows_stay_unknown_without_invented_context_limits(tmp_path, monkeypatch):
    host = replace(
        configured(),
        context_window=None,
        worker_route=replace(configured().route("worker"), context_window=None),
    )
    child = container_settings(await captured_request(host, tmp_path, monkeypatch))
    for role in ["main", "worker"]:
        assert child.route(role).context_window is None
        assert child.threshold_for(role) is None


async def test_saved_container_capacity_queues_compaction_after_real_turn_usage(
    store, tmp_path, monkeypatch
):
    host = configured()
    child = container_settings(await captured_request(host, tmp_path, monkeypatch))

    class UsageModel:
        model = "protocol-fixture"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            yield ModelEvent("text", "Delivered")
            yield ModelEvent("usage", {"inputTokens": 14500, "outputTokens": 10})

    model = UsageModel()
    runtime = Runtime(store, model, settings=child)
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "finish", "Small input")
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
                (receipt["turnId"],),
            )
        )
        turn = await runtime.mailbox.claim(job)
        await runtime.loop.run(turn, "main")
        compact = await store.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE kind='context.compact'")
        )
        assert compact and compact["state"] == "queued"
        assert model.calls == 1
        plan = await runtime.context.project("alice", c["id"])
        assert plan["contextWindow"] == 24000
        assert plan["compactionThreshold"] == 14400
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"main_window": True},
        {"main_window": -1},
        {"worker_window": 100_000_001},
        {"reserve_tokens": False},
        {"keep_recent_tokens": 0},
        {"compaction_ratio": 0},
        {"compaction_ratio": 1},
        {"compaction_ratio": True},
        {"compaction_ratio": float("nan")},
        {"endpoint": "https://untrusted.invalid"},
    ],
)
def test_shared_context_metadata_is_required_and_bounded(raw):
    from roami_agent.improvement.evaluation.execution.container_context import model_context

    raw = {**model_context(configured()), **raw} if raw else raw
    with pytest.raises(DomainError, match="RSI_CONTAINER_MODEL_CONTEXT_INVALID"):
        container_settings({"shared_daily_limit": True, "model_context": raw})


def test_explicit_legacy_requests_keep_their_original_context_behavior():
    child = container_settings({"shared_daily_limit": False})
    assert child.route("main").context_window is None
    assert child.route("worker").context_window is None
    assert child.compaction_ratio == 0.75
