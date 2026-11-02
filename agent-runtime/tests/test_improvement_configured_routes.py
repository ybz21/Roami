"""Shared RSI inherits node routes; CLI and archived profiles cannot choose models."""

import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from test_improvement_artifact_daily_policy import configured_settings
from test_improvement_artifact_review import certificate, pack, profile, rating
from test_improvement_codex_gateway import payload

from roami_agent.app import Runtime
from roami_agent.improvement.evaluation.artifact_review import ArtifactReviewer
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.evaluation.execution.executors import (
    NativeFilesExecutor,
    ProtocolFixtureModel,
)
from roami_agent.improvement.evaluation.protocol_suite import protocol_suite
from roami_agent.improvement.integrations.codex_gateway import CodexTextGateway, gateway_plan
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.factory import configured_provider


@pytest.mark.parametrize("cap", [None, 7000])
async def test_codex_wire_alias_and_parameters_cannot_override_saved_chat_request(cap):
    settings = replace(
        configured_settings(),
        model_parameters={"reasoning_effort": "low", **({"max_tokens": cap} if cap else {})},
        context_window=64000,
    )
    seen = []

    def transport(request):
        seen.append(json.loads(request.content))
        events = [
            {
                "choices": [
                    {"delta": {"content": '{"document":"configured"}'}, "finish_reason": None}
                ]
            },
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        ]
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content="".join("data: " + json.dumps(event) + "\n\n" for event in events)
            + "data: [DONE]\n\n",
        )

    def factory(effective, role):
        assert role == "main" and effective.route(role) == settings.route(role)
        return configured_provider(
            effective, role, client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
        )

    plan = await gateway_plan(
        settings, {"model": "gpt-6.1-sol", "model_reasoning_effort": "high"}, factory=factory
    )
    outcome = {}
    async with (
        CodexTextGateway(plan, "review", outcome, 30) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        response = await client.post(
            bridge.url + "/responses",
            headers={"Authorization": "Bearer " + bridge.secret},
            json={**payload(), "reasoning": {"effort": "high"}, "max_output_tokens": 512},
        )
    assert "response.completed" in response.text and len(seen) == 1
    assert seen[0]["model"] == settings.model and seen[0]["reasoning_effort"] == "low"
    assert seen[0].get("max_tokens") == cap
    assert outcome["metrics"]["tokens"] == 14


async def test_daily_artifact_profile_cannot_override_either_saved_role():
    settings = replace(
        configured_settings(),
        model_parameters={"reasoning_effort": "low", "max_tokens": 9000},
        image_limits={"max_width": 900},
    )
    settings = replace(
        settings,
        worker_route=replace(
            settings.route("worker"),
            max_retries=3,
            parameters={"temperature": 0.4},
            image_limits={"max_width": 800},
        ),
    )
    raw = profile()
    for row in raw["reviewers"]:
        row["route"].update(
            endpoint="https://unselected.invalid/v1",
            parameters={"reasoning_effort": "high", "max_tokens": 512},
            max_retries=0,
        )
    seen = []

    def factory(effective, role):
        seen.append((role, effective.route(role)))
        return ProtocolFixtureModel([{"text": json.dumps(rating())}])

    judge = ArtifactReviewer(
        settings, raw, calibrated=False, provider_factory=factory, shared_daily_limit=True
    )
    assert judge.routes == {
        "artifact_a": settings.route("main"),
        "artifact_b": settings.route("worker"),
    }
    assert len(await judge.rate(pack(), judge.budget(), [])) == 2
    assert seen == [(role, settings.route(role)) for role in ("main", "worker")]
    assert (
        ArtifactReviewer(
            settings, profile(), calibrated=False, shared_daily_limit=True
        ).route_hashes
        == judge.route_hashes
    )


@pytest.mark.parametrize(
    "fault,code",
    [("images", "MODEL_IMAGES_UNSUPPORTED"), ("duplicate", "RSI_INDEPENDENT_RATERS_REQUIRED")],
)
def test_profile_cannot_enable_images_or_invent_a_second_model(fault, code):
    settings = configured_settings()
    worker = settings.route("worker")
    worker = (
        replace(worker, capabilities={})
        if fault == "images"
        else replace(worker, name=settings.model)
    )
    with pytest.raises(DomainError, match=code):
        ArtifactReviewer(
            replace(settings, worker_route=worker),
            profile(),
            calibrated=False,
            shared_daily_limit=True,
        )


def test_previous_calibration_cannot_authorize_changed_saved_route():
    settings = configured_settings()
    draft = ArtifactReviewer(settings, profile(), calibrated=False, shared_daily_limit=True)
    raw = {**profile(), "certificate": certificate(draft.route_hashes)}
    with pytest.raises(DomainError, match="RSI_ARTIFACT_CALIBRATION_CHANGED"):
        ArtifactReviewer(replace(settings, model="changed-main"), raw, shared_daily_limit=True)


@pytest.mark.parametrize(
    "override", ["main", "worker", "memory", "reasoning", "capability", "retry", "output"]
)
def test_daily_container_rejects_temporary_routes_and_generation_overrides(override):
    settings = configured_settings()
    if override in {"main", "worker", "memory"}:
        actual = "main" if override == "main" else "worker"
        kwargs = {override + "_route": replace(settings.route(actual), name="unselected")}
    elif override == "reasoning":
        kwargs = {"generation_overrides": {"worker": {"reasoning_effort": "high"}}}
    elif override == "output":
        kwargs = {"output_caps": {"main": 512}}
    else:
        route = settings.route("worker")
        kwargs = {
            "worker_route": replace(
                route,
                **(
                    {"capabilities": {"images": False}}
                    if override == "capability"
                    else {"max_retries": 0}
                ),
            )
        }
    with pytest.raises(DomainError, match="RSI_POLICY_OUT_OF_RANGE"):
        ContainerExecutor(settings, shared_daily_limit=True, **kwargs)


async def test_daily_native_execution_keeps_saved_timeouts_and_retries(tmp_path):
    settings = configured_settings()
    seen = {}

    def factory(effective, role):
        actual = "main" if role == "main" else "worker"
        seen[role] = effective.route(actual)
        return ProtocolFixtureModel([{"text": "configured fixture"}])

    case = protocol_suite()["cases"][0]
    await NativeFilesExecutor(settings, provider_factory=factory, shared_daily_limit=True).run(
        case, {}, tmp_path
    )
    assert seen == {
        "main": settings.route("main"),
        "worker": settings.route("worker"),
        "memory": settings.route("worker"),
    }


@pytest.mark.parametrize(
    "role,actual",
    [
        ("main", "main"),
        ("worker", "worker"),
        ("memory", "worker"),
        ("artifact_a", "main"),
        ("artifact_b", "worker"),
    ],
)
def test_runtime_provider_binds_rater_to_the_correct_saved_role(monkeypatch, role, actual):
    settings = configured_settings()
    seen = []
    monkeypatch.setattr(
        "roami_agent.app.configured_provider", lambda cfg, name: seen.append((cfg, name))
    )
    Runtime.improvement_provider(SimpleNamespace(), settings, role)
    assert seen == [(settings, actual)]


@pytest.mark.parametrize("with_settings", [False, True])
async def test_native_only_diagnostic_does_not_load_an_unused_rater_profile(
    tmp_path, monkeypatch, with_settings
):
    from test_improvement_control import suite_file

    from roami_agent.improvement.domain.contracts import digest
    from roami_agent.improvement.service import ImprovementStatus
    from roami_agent.improvement.workflows.pipeline_runner import (
        enqueue_diagnostic,
        execute_diagnostic,
    )

    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", suite_file(tmp_path))
    service.control.save(
        "local", {**service.control.preferences("local"), "suite_id": "data", "machine_ids": ["a"]}
    )
    path = service.ledger.path.parent / "artifact-review" / digest("local")[:24] / "profile.json"
    path.parent.mkdir(mode=0o700, parents=True)
    path.write_text("unused invalid profile")
    monkeypatch.setattr(
        ArtifactReviewer,
        "load",
        lambda *args, **kwargs: pytest.fail("Unused rater must not block a native case"),
    )

    class Executor:
        model_hash = "a" * 64
        artifact_reviewer = None

        def __init__(self, settings, **kwargs):
            pass

        async def preflight(self):
            return {"environment_hash": "b" * 64}

        async def run(self, case, policy, root):
            return {
                "grade": {"passed": True},
                "metrics": {"tokens": 0, "model_calls": 0, "requests": [], "request_attempts": 0},
            }

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.execution.containers.ContainerExecutor", Executor
    )
    settings = configured_settings()
    run = enqueue_diagnostic(
        service,
        "local",
        {"request_key": "native-only", "case_ids": ["a"]},
        settings if with_settings else None,
    )
    claimed = service.control.claim()
    await execute_diagnostic(
        SimpleNamespace(settings=SimpleNamespace(current=settings)), service, claimed
    )
    value = service.runs.get("local", run["id"])
    assert value["snapshot"]["artifact_review"]["hash"] is None
    assert value["cases"][0]["state"] == "passed"
