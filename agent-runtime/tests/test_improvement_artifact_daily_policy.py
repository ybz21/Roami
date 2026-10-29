"""Daily artifact review shares model admission while retaining calibration provenance."""

import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from test_improvement_artifact_review import certificate, pack, profile, rating

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest
from roami_agent.improvement.evaluation.artifact_review import ArtifactReviewer, calibrate_artifacts
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.model_routes import ModelRoute
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


def configured_settings(parameters=None):
    return Settings(
        endpoint="https://configured.invalid/v1",
        model="saved-main",
        model_capabilities={"images": True},
        model_parameters=parameters or {},
        worker_route=ModelRoute(
            "https://configured.invalid/v1",
            "saved-worker",
            "SAVED_WORKER_KEY",
            90,
            capabilities={"images": True},
            parameters=parameters or {},
        ),
    )


@pytest.mark.parametrize("configured_cap", [None, 8192])
@pytest.mark.parametrize("legacy_limits", [True, False])
async def test_daily_raters_use_model_page_cap_and_can_exceed_the_old_profile_budget(
    configured_cap,
    legacy_limits,
):
    parameters = {} if configured_cap is None else {"max_tokens": configured_cap}
    settings = configured_settings(parameters)
    raw = profile()
    legacy_token_limit = raw["max_tokens"]
    raw["output_tokens"] = 4096
    if not legacy_limits:
        raw.pop("max_tokens")
        raw.pop("output_tokens")
    for rater in raw["reviewers"]:
        rater["route"]["parameters"] = {"max_tokens": 2048, "temperature": 0}
    observed = []

    class Provider:
        model = "daily-policy-fixture"

        async def stream(self, *args):
            yield ModelEvent("text", json.dumps(rating()))
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 20000,
                    "outputTokens": 20000,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    def factory(effective, role):
        observed.append(effective.route("main").parameters)
        return Provider()

    judge = ArtifactReviewer(
        settings, raw, calibrated=False, provider_factory=factory, shared_daily_limit=True
    )
    budget, journal = judge.budget(), []
    ratings = await judge.rate(pack(), budget, journal)
    assert len(ratings) == 2 and budget.metrics()["tokens"] == 80000 > legacy_token_limit
    assert observed == [parameters] * 2
    assert [r["output_cap"] for r in journal] == [configured_cap or 0] * 2
    changed = copy.deepcopy(raw)
    changed.update(max_tokens=64000, output_tokens=1024)
    assert (
        judge.content_hash
        == ArtifactReviewer(
            settings, changed, calibrated=False, shared_daily_limit=True
        ).content_hash
    )
    assert judge.route_hashes != ArtifactReviewer(settings, changed, calibrated=False).route_hashes


@pytest.mark.parametrize("shared", [False, True])
def test_loaded_rater_uses_the_same_policy_as_preflight_and_rejects_changed_routes(
    tmp_path, shared
):
    settings, raw = configured_settings(), profile()
    draft = ArtifactReviewer(settings, raw, calibrated=False, shared_daily_limit=shared)
    cert = certificate(draft.route_hashes)
    cert["provider_mode"] = "live_models"  # Synthetic certificate validation fixture.
    directory = tmp_path / "artifact-review" / digest("alice")[:24]
    directory.mkdir(mode=0o700, parents=True)
    for name, value in [
        ("profile.json", {**raw, "certificate_file": "certificate.json"}),
        ("certificate.json", cert),
    ]:
        path = directory / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    loaded = ArtifactReviewer.load(settings, tmp_path, "alice", shared_daily_limit=shared)
    assert loaded.shared_daily_limit is shared
    assert loaded.route_hashes == draft.route_hashes
    assert (
        loaded.content_hash
        == ArtifactReviewer(
            settings, {**raw, "certificate": cert}, shared_daily_limit=shared
        ).content_hash
    )
    with pytest.raises(DomainError, match="RSI_ARTIFACT_CALIBRATION_CHANGED"):
        ArtifactReviewer.load(settings, tmp_path, "alice", shared_daily_limit=not shared)


async def test_daily_calibration_has_no_local_token_reservation_and_never_replays(tmp_path):
    evidence = tmp_path / "pack.json"
    evidence.write_text(json.dumps(pack()))
    evidence.chmod(0o600)
    anchors = []
    for family in ("presentation", "plan", "web"):
        for score in (1, 1, 3, 3):
            anchors.append(
                {
                    "id": family + str(len(anchors)),
                    "family": family,
                    "human_reference": True,
                    "human_rater": "Synthetic test label",
                    "expected": dict.fromkeys(DIMENSIONS, score),
                    "evidence_file": str(evidence),
                    "evidence_hash": pack()["content_hash"],
                }
            )
    calls = []

    class Provider:
        model = "daily-calibration-fixture"

        def __init__(self, score):
            self.score = score

        async def stream(self, *args):
            yield ModelEvent("text", json.dumps(rating(self.score)))
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 50000,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    def factory(effective, role):
        assert "max_tokens" not in effective.route("main").parameters
        score = (1, 1, 3, 3)[(len(calls) // 2) % 4]
        calls.append(role)
        return Provider(score)

    root = tmp_path / "ratings"
    result = await calibrate_artifacts(
        configured_settings(),
        profile(),
        anchors,
        root,
        token_limit=1,
        provider_factory=factory,
        shared_daily_limit=True,
    )
    assert result["passed"] and result["provider_mode"] == "protocol_fixture"
    saved = json.loads(Path(result["certificate"]).read_text())
    assert saved["model_page_routes"] == {
        role: asdict(configured_settings().route(role)) for role in ("main", "worker")
    }
    assert len(calls) == 24 and result["tokens"] == 24 * 50001
    starts = [json.loads(p.read_text()) for p in root.glob("*/started.json")]
    assert len(starts) == 12
    assert all(
        s["reserved_tokens"] is None and s["spending_policy"] == "shared_model_daily"
        for s in starts
    )
    with pytest.raises(FileExistsError):
        await calibrate_artifacts(
            configured_settings(),
            profile(),
            anchors,
            root,
            provider_factory=factory,
            shared_daily_limit=True,
        )
    assert len(calls) == 24


@pytest.mark.parametrize(
    ("shared", "cap", "legacy_limits"),
    [
        (False, None, True),
        (True, None, True),
        (True, 8192, True),
        (True, None, False),
        (True, 8192, False),
    ],
)
async def test_configure_command_installs_the_exact_calibrated_policy(
    tmp_path, shared, cap, legacy_limits
):
    from types import SimpleNamespace

    from roami_agent.improvement.entrypoints.cli import execute

    parameters = {} if cap is None else {"max_tokens": cap}
    settings = configured_settings(parameters)
    raw = profile()
    if not legacy_limits:
        raw.pop("max_tokens")
    draft = ArtifactReviewer(settings, raw, calibrated=False, shared_daily_limit=shared)
    cert = certificate(draft.route_hashes)
    cert["provider_mode"] = "live_models"  # Synthetic command-validation fixture only.
    if shared:
        cert.update(
            spending_policy="shared_model_daily",
            model_page_output_tokens=cap,
            model_page_routes={role: asdict(settings.route(role)) for role in ("main", "worker")},
        )
    inputs = []
    for name, value in [("profile.json", raw), ("certificate.json", cert)]:
        path = tmp_path / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        inputs.append(path)
    args = SimpleNamespace(
        command="configure-artifact-review",
        profile=inputs[0],
        certificate=inputs[1],
        ledger=tmp_path / "ledger" / "ledger.sqlite3",
        owner="alice",
    )
    result = await execute(args)
    loaded = ArtifactReviewer.load(settings, args.ledger.parent, "alice", shared_daily_limit=shared)
    assert result["configured"] and loaded.content_hash == result["profile_hash"]
    assert loaded.route_hashes == draft.route_hashes
    assert loaded.shared_daily_limit is shared
    assert loaded.budget().limits["tokens"] == (0 if shared else raw["max_tokens"])


async def test_profile_without_token_fields_previews_and_queues_on_daily_policy(tmp_path):
    from test_improvement_control import suite_file

    from roami_agent.improvement.evaluation.contracts import freeze_suite, load_suite
    from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
    from roami_agent.improvement.presentation.experiment_preview import preview
    from roami_agent.improvement.service import ImprovementStatus
    from roami_agent.improvement.workflows.pipeline_runner import enqueue_diagnostic

    service = ImprovementStatus(tmp_path)
    service.ledger.shared_daily_limit = True
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    base = load_suite(suite_file(tmp_path))["cases"][0]
    case = {**base, "id": "DEMO-01"}
    suite_path = tmp_path / "rated.json"
    suite_path.write_text(json.dumps(freeze_suite("rated", [case])))
    service.control.register_suite("local", suite_path)
    service.control.save(
        "local", {**service.control.preferences("local"), "suite_id": "rated", "machine_ids": ["a"]}
    )
    raw = profile()
    raw.pop("max_tokens")
    settings = configured_settings()
    judge = ArtifactReviewer(settings, raw, calibrated=False, shared_daily_limit=True)
    cert = certificate(judge.route_hashes)
    cert["provider_mode"] = "live_models"  # Synthetic profile-loading fixture only.
    directory = service.ledger.path.parent / "artifact-review" / digest("local")[:24]
    directory.mkdir(mode=0o700, parents=True)
    for name, value in [
        ("profile.json", {**raw, "certificate_file": "certificate.json"}),
        ("certificate.json", cert),
    ]:
        path = directory / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    assert preview(service, "local", settings)["reservation_tokens"] is None
    run = enqueue_diagnostic(
        service, "local", {"request_key": "no-token-fields", "case_ids": ["DEMO-01"]}, settings
    )
    assert run["id"]
    executor = ContainerExecutor(settings, artifact_reviewer=judge, shared_daily_limit=True)
    assert executor.reservation_tokens(case) == 0


@pytest.mark.parametrize("fault", ["policy", "cap"])
async def test_configure_command_rejects_invalid_daily_certificate_snapshot_before_writing(
    tmp_path, fault
):
    from types import SimpleNamespace

    from roami_agent.improvement.entrypoints.cli import execute

    cert = {"spending_policy": "shared_model_daily", "model_page_output_tokens": None}
    cert["spending_policy" if fault == "policy" else "model_page_output_tokens"] = "invalid"
    for name, value in [("profile.json", profile()), ("certificate.json", cert)]:
        p = tmp_path / name
        p.write_text(json.dumps(value))
        p.chmod(0o600)
    args = SimpleNamespace(
        command="configure-artifact-review",
        profile=tmp_path / "profile.json",
        certificate=tmp_path / "certificate.json",
        ledger=tmp_path / "ledger" / "ledger.sqlite3",
        owner="alice",
    )
    with pytest.raises(DomainError):
        await execute(args)
    assert not args.ledger.parent.exists()


async def test_daily_calibration_requires_a_bound_gateway_before_any_work(tmp_path):
    root = tmp_path / "ratings"
    with pytest.raises(DomainError, match="RSI_SHARED_MODEL_GATEWAY_REQUIRED"):
        await calibrate_artifacts(Settings(), profile(), [], root, shared_daily_limit=True)
    assert not root.exists()


async def test_daily_rater_unknown_usage_still_stops_the_second_rater():
    calls = []

    class Provider:
        model = "unknown-usage-fixture"

        async def stream(self, *args):
            yield ModelEvent("text", json.dumps(rating()))

    def factory(settings, role):
        calls.append(role)
        return Provider()

    judge = ArtifactReviewer(
        configured_settings(),
        profile(),
        calibrated=False,
        provider_factory=factory,
        shared_daily_limit=True,
    )
    budget = judge.budget()
    with pytest.raises(DomainError, match="RSI_USAGE_UNKNOWN"):
        await judge.rate(pack(), budget, [])
    assert calls == ["artifact_a"] and budget.unknown and budget.metrics()["tokens"] is None
