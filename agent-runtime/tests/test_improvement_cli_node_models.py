"""Standalone inference keeps node routes, gateway admission and the model-page quota."""

import json
import os
from types import SimpleNamespace

import pytest
from test_improvement_artifact_review import profile
from test_local_go_gateway import gateway_fixture
from test_model_proxy import consume

from roami_agent.improvement.entrypoints import cli
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.protocol.errors import DomainError, ModelAdmissionRejected


def node(tmp_path, monkeypatch):
    root = tmp_path / "node"
    (root / "agents").mkdir(parents=True)
    config = root / "agent.toml"
    config.write_text(
        '[model]\nendpoint="https://old.invalid/v1"\nname="old-main"\n'
        "max_retries=3\nparameters={temperature=0.4,max_tokens=8192}\n"
    )
    saved = root / "agents/model-settings.json"
    saved.write_text(
        json.dumps(
            {
                "connection": {"baseUrl": "https://saved.invalid/v1"},
                "main": {"model": "saved-main", "images": True, "contextWindow": 65536},
                "worker": {"model": "saved-worker", "images": True, "contextWindow": 32768},
                "proxy": {"dailyLimit": 100, "currency": "CNY"},
            }
        )
    )
    saved.chmod(0o600)
    monkeypatch.setenv("ROAMI_MODEL_GATEWAY_SOCKET", str(tmp_path / "model.sock"))

    async def binding(argv, **options):
        assert argv[1:] == ["agent", "gateway", "binding", "--data-root", str(root)]
        socket = os.environ.get("ROAMI_MODEL_GATEWAY_SOCKET")
        return {
            "exitCode": 0 if socket else 1,
            "stdout": json.dumps({"data": {"socket": socket}}),
            "stderr": "",
        }

    monkeypatch.setattr("roami_agent.improvement.entrypoints.node_models.execute", binding)

    return root, config, saved


def calibration_args(tmp_path, root, config):
    for name, value in [("profile.json", profile()), ("anchors.json", [])]:
        path = tmp_path / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    return SimpleNamespace(
        command="calibrate-artifacts",
        agent_config=config,
        data_root=root,
        profile=tmp_path / "profile.json",
        anchors=tmp_path / "anchors.json",
        output=tmp_path / "ratings",
        token_limit=1,
    )


async def test_calibration_cli_inherits_saved_routes_and_ignores_legacy_token_limit(
    tmp_path, monkeypatch
):
    root, config, saved = node(tmp_path, monkeypatch)
    before = saved.read_bytes()

    async def calibrate(settings, profile, anchors, output, **options):
        assert settings.model == "saved-main"
        assert settings.route("worker").name == "saved-worker"
        assert settings.route("worker").context_window == 32768
        assert settings.route("main").context_window == 65536
        assert settings.route("main").max_retries == 3
        assert settings.route("main").parameters == {"temperature": 0.4, "max_tokens": 8192}
        assert settings.route("main").capabilities["images"] is True
        assert options["shared_daily_limit"] is True
        assert options["provider_mode"] == "live_models"
        assert "token_limit" not in options
        assert callable(options["provider_factory"])
        return {"checked": True}

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.artifact_review.calibrate_artifacts", calibrate
    )
    assert await cli.execute(calibration_args(tmp_path, root, config)) == {"checked": True}
    assert saved.read_bytes() == before and not (tmp_path / "ratings").exists()


@pytest.mark.parametrize("command", ["calibrate-artifacts", "cycle"])
async def test_cli_without_daily_gateway_stops_before_model_or_case_execution(
    tmp_path, monkeypatch, command
):
    root, config, _ = node(tmp_path, monkeypatch)
    monkeypatch.delenv("ROAMI_MODEL_GATEWAY_SOCKET")
    args = (
        calibration_args(tmp_path, root, config)
        if command == "calibrate-artifacts"
        else cycle_args(tmp_path, root, config)
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Unbound CLI must not create a provider or run a case")

    monkeypatch.setattr("roami_agent.providers.factory.configured_provider", forbidden)
    monkeypatch.setattr(cli, "NativeFilesExecutor", forbidden)
    with pytest.raises(DomainError, match="RSI_SHARED_MODEL_GATEWAY_REQUIRED"):
        await cli.execute(args)
    assert not (tmp_path / "ratings").exists()


async def test_cli_calibration_private_quota(tmp_path, monkeypatch):
    root, config, _ = node(tmp_path, monkeypatch)
    seen = []

    async def calibrate(settings, *args, **options):
        provider = options["provider_factory"](settings, "main")
        try:
            with pytest.raises(ModelAdmissionRejected, match="MODEL_PROXY_DAILY_LIMIT"):
                await consume(provider)
        finally:
            await provider.close()
        return {"quotaBlocked": True}

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.artifact_review.calibrate_artifacts", calibrate
    )
    async with gateway_fixture(
        str(tmp_path / "model.sock"), seen, status=402, code="MODEL_PROXY_DAILY_LIMIT"
    ):
        result = await cli.execute(calibration_args(tmp_path, root, config))
    assert result["quotaBlocked"] and len(seen) == 1
    _, headers, body = seen[0]
    assert headers["x-roami-model-upstream"] == "https://saved.invalid/v1/chat/completions"
    assert body["model"] == "saved-main" and body["max_tokens"] == 8192
    assert body["temperature"] == 0.4


def cycle_args(tmp_path, root, config, mode="native_files"):
    case = {
        "id": "cli-fixture",
        "category": "CODE",
        "layer": "authored_real",
        "split": "development",
        "prompt": "Return 1",
        "counts_as_delivery": False,
        "files": {},
        "limits": {"seconds": 30, "tokens": 1, "requests": 1},
        "judge": {"kind": "numeric", "expected": 1},
    }
    (tmp_path / "suite.json").write_text(json.dumps(freeze_suite("cli", [case])))
    value = {
        "schema_version": 1,
        "owner": "local",
        "suite": "suite.json",
        "model_config": str(config),
        "data_root": str(root),
        "ledger": "private/ledger.sqlite3",
        "output_root": "private/runs",
        "machine": {"id": "node", "mode": mode, "cache_mode": "uncontrolled"},
    }
    if mode == "protocol_fixture":
        value["daily_budget"] = {"tokens": 2, "episodes": 2}
    path = tmp_path / "cycle.json"
    path.write_text(json.dumps(value))
    return SimpleNamespace(command="cycle", config=path)


async def test_native_cycle_uses_node_settings_and_needs_no_rsi_budget(tmp_path, monkeypatch):
    root, config, saved = node(tmp_path, monkeypatch)
    before = saved.read_bytes()

    class Executor:
        model_hash = "fixture"

        def __init__(self, settings, **options):
            assert (
                settings.model == "saved-main" and settings.route("worker").name == "saved-worker"
            )
            assert options == {"fixture": False, "shared_daily_limit": True}

    async def run(**options):
        assert options["ledger"].shared_daily_limit is True
        assert options["daily_tokens"] == options["daily_episodes"] == 0
        return {"dailyPolicy": True}

    monkeypatch.setattr(cli, "NativeFilesExecutor", Executor)
    monkeypatch.setattr(cli, "run_cycle", run)
    assert await cli.execute(cycle_args(tmp_path, root, config)) == {"dailyPolicy": True}
    assert saved.read_bytes() == before


async def test_protocol_fixture_cycle_stays_offline_without_node_binding(tmp_path, monkeypatch):
    root, config, _ = node(tmp_path, monkeypatch)
    monkeypatch.delenv("ROAMI_MODEL_GATEWAY_SOCKET")

    class Executor:
        model_hash = "fixture"

        def __init__(self, settings, **options):
            assert options["fixture"] is True
            assert options.get("shared_daily_limit", False) is False

    async def run(**options):
        assert getattr(options["ledger"], "shared_daily_limit", False) is False
        assert options["daily_tokens"] == options["daily_episodes"] == 0
        return {"fixture": True}

    monkeypatch.setattr(cli, "NativeFilesExecutor", Executor)
    monkeypatch.setattr(cli, "run_cycle", run)
    assert await cli.execute(cycle_args(tmp_path, root, config, "protocol_fixture")) == {
        "fixture": True
    }


@pytest.mark.parametrize("fault", ["permission", "malformed"])
async def test_invalid_saved_settings_fail_before_calibration(tmp_path, monkeypatch, fault):
    root, config, saved = node(tmp_path, monkeypatch)
    if fault == "permission":
        saved.chmod(0o644)
    else:
        saved.write_text('{"main":')

    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid saved settings must not enter calibration")

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.artifact_review.calibrate_artifacts", forbidden
    )
    with pytest.raises(DomainError, match="MODEL_SETTINGS_"):
        await cli.execute(calibration_args(tmp_path, root, config))
    assert not (tmp_path / "ratings").exists()


async def test_cli_native_runtime_retains_provider_parameters_past_old_case_budget(
    tmp_path, monkeypatch
):
    from roami_agent.improvement.evaluation.execution.executors import ProtocolFixtureModel
    from roami_agent.improvement.persistence.ledger import Ledger

    root, config, _ = node(tmp_path, monkeypatch)
    observed = []

    def provider(settings, role):
        route = settings.route(role)
        observed.append((role, route))
        return ProtocolFixtureModel([{"text": "1" if role == "main" else '{"memories":[]}'}])

    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.execution.executors.configured_provider", provider
    )
    args = cycle_args(tmp_path, root, config)
    result = await cli.execute(args)
    assert result["admitted"] and result["counts"]["baseline"]["passed"] == 1
    assert {role for role, _ in observed} == {"main", "worker"}
    assert all(
        route.parameters == {"temperature": 0.4, "max_tokens": 8192} for _, route in observed
    )
    assert all(route.max_retries == 3 for _, route in observed)
    assert {route.name for _, route in observed} == {"saved-main", "saved-worker"}
    detail = Ledger(tmp_path / "private/ledger.sqlite3").get("local", result["cycle_id"])
    assert detail["manifest"]["spending_policy"] == "shared_model_daily"
    assert detail["manifest"]["reserved_tokens"] == 0
    assert all(t["metrics"]["observed_tokens"] > 1 for t in detail["trials"])


async def test_cli_automatic_capacity_uses_saved_model_catalog(tmp_path, monkeypatch):
    root, config, saved = node(tmp_path, monkeypatch)
    value = json.loads(saved.read_text())
    value["main"]["contextWindow"] = value["worker"]["contextWindow"] = None
    saved.write_text(json.dumps(value))
    seen = []

    async def catalog(endpoint, credentials):
        seen.append(endpoint)
        return {"saved-main": 123456, "saved-worker": 65432}

    async def calibrate(settings, *args, **kwargs):
        assert settings.route("main").context_window == 123456
        assert settings.route("worker").context_window == 65432
        return {"resolved": True}

    monkeypatch.setattr("roami_agent.server.model_settings.fetch_catalog", catalog)
    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.artifact_review.calibrate_artifacts", calibrate
    )
    assert await cli.execute(calibration_args(tmp_path, root, config)) == {"resolved": True}
    assert seen
    assert json.loads(saved.read_text())["main"]["contextWindow"] is None


@pytest.mark.parametrize("gateway_bound", [True, False])
async def test_cli_external_worker_cannot_bypass_node_routes_or_quota(
    tmp_path, monkeypatch, gateway_bound
):
    root, config, _ = node(tmp_path, monkeypatch)
    if not gateway_bound:
        monkeypatch.delenv("ROAMI_MODEL_GATEWAY_SOCKET")
    args = cycle_args(tmp_path, root, config, "external")
    data = json.loads(args.config.read_text())
    data["machine"].update(argv=["/must-not-spawn-external"], model_hash="external-route")
    data["daily_budget"] = {"tokens": 1000000, "episodes": 100}
    args.config.write_text(json.dumps(data))

    async def forbidden(*args, **kwargs):
        pytest.fail("External worker must not be spawned")

    monkeypatch.setattr("asyncio.create_subprocess_exec", forbidden)
    with pytest.raises(DomainError, match="RSI_SHARED_MODEL_GATEWAY_REQUIRED"):
        await cli.execute(args)
