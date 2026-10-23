"""Codex execution receipts and aggregated Issue publication, without paid/API calls."""

import json

import pytest
from test_improvement_workflow import (
    MACHINE,
    SOURCE,
    FixtureExecutor,
    Reviewer,
    make_suite,
    seed_review_for_stage_fixture,
    setup,
)

from roami_agent.improvement.behavior_observer import observe_cycle
from roami_agent.improvement.codex_roles import codex_configuration, codex_json, completed_result
from roami_agent.improvement.contracts import digest
from roami_agent.improvement.control import ImprovementControl
from roami_agent.improvement.cycle import run_cycle
from roami_agent.improvement.github_issues import publish_issue, sync_issue
from roami_agent.improvement.github_publication import configure_publication
from roami_agent.improvement.review_report import compose_issue, finding_id
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


def codex_events(*, text='{"ok":true}', tokens=100, extra=None):
    events = [
        {"type": "thread.started", "thread_id": "codex-fixture-thread"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
        {
            "type": "turn.completed",
            "usage": {"input_tokens": tokens, "cached_input_tokens": 10, "output_tokens": 20},
        },
    ]
    if extra:
        events.insert(2, extra)
    return "\n".join(json.dumps(e) for e in events)


async def test_codex_roles_use_native_cli_without_tools_and_reuse_paid_receipt(
    tmp_path, monkeypatch
):
    w, cfg, _, _, _ = await setup(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("GH_TOKEN", "fixture-do-not-forward")
    action = {"id": "codex-review", "owner": "owner", "kind": "review"}
    calls = []

    async def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return {"stdout": codex_events(), "stderr": "", "exitCode": 0}

    first = await codex_json(
        w, action, cfg, "packet-1", [{"role": "user", "content": "fixture"}], runner=runner
    )
    second = await codex_json(
        w, action, cfg, "packet-1", [{"role": "user", "content": "fixture"}], runner=runner
    )
    assert first == second and len(calls) == 1
    args, kwargs = calls[0]
    assert args[:3] == ["codex", "exec", "--json"]
    assert "read-only" in args and "--ignore-user-config" in args
    assert "features.shell_tool=false" in args and "features.hooks=false" in args
    assert "GH_TOKEN" not in kwargs["env"]
    assert kwargs["cwd"] != tmp_path / "repo"
    assert first["executor"] == "codex" and first["thread_id"] == "codex-fixture-thread"
    assert first["metrics"]["tokens"] == 120
    assert (kwargs["cwd"] / "process.json").stat().st_mode & 0o077 == 0
    with pytest.raises(DomainError, match="CONTEXT_CHANGED"):
        await codex_json(
            w, action, cfg, "packet-1", [{"role": "user", "content": "changed"}], runner=runner
        )
    assert len(calls) == 1


async def test_unknown_codex_call_never_replays_and_blocks_other_paid_calls(tmp_path, monkeypatch):
    w, cfg, _, _, _ = await setup(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty"))
    calls = []

    async def interrupted(*args, **kwargs):
        calls.append(1)
        raise TimeoutError

    action = {"id": "interrupted-codex", "owner": "owner", "kind": "repair"}
    with pytest.raises(TimeoutError):
        await codex_json(w, action, cfg, "patch", [], runner=interrupted)
    for key in ("patch", "other-packet"):
        with pytest.raises(DomainError, match="UNKNOWN_OPERATION"):
            await codex_json(w, action, cfg, key, [], runner=interrupted)
    assert calls == [1]


async def test_codex_overrun_is_accounted_once_then_stops(tmp_path, monkeypatch):
    w, cfg, _, _, _ = await setup(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty"))
    calls = []

    async def overrun(*args, **kwargs):
        calls.append(1)
        return {"stdout": codex_events(tokens=cfg["model_tokens"] + 1), "stderr": "", "exitCode": 0}

    action = {"id": "overrun", "owner": "owner", "kind": "issue"}
    for _ in range(2):
        with pytest.raises(DomainError, match="TOKEN_LIMIT_EXCEEDED"):
            await codex_json(w, action, cfg, "plan", [], runner=overrun)
    with pytest.raises(DomainError, match="UNKNOWN_OPERATION"):
        await codex_json(w, action, cfg, "new-plan", [], runner=overrun)
    assert len(calls) == 1
    assert w.snapshot("owner")["model_cost"]["observed_tokens"] == cfg["model_tokens"] + 21


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda events: [e for e in events if e["type"] != "turn.completed"], "TURN_INCOMPLETE"),
        (lambda events: events + [{"type": "turn.failed"}], "TURN_INCOMPLETE"),
        (
            lambda events: (
                events + [{"type": "item.completed", "item": {"type": "command_execution"}}]
            ),
            "UNEXPECTED_MODEL_TOOL",
        ),
        (lambda events: [e for e in events if e["type"] != "thread.started"], "IDENTITY_REQUIRED"),
    ],
)
def test_codex_requires_identity_terminal_usage_and_no_tools(mutate, code):
    events = [json.loads(line) for line in codex_events().splitlines()]
    with pytest.raises(DomainError, match=code):
        completed_result("\n".join(json.dumps(e) for e in mutate(events)))


def test_codex_preserves_model_and_env_references_without_personal_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("FIXTURE_CODEX_KEY", "fixture-only-value")
    (tmp_path / "config.toml").write_text(
        'model="fixture-model"\nmodel_provider="fixture"\n[model_providers.fixture]\nname="Fixture"\nbase_url="https://example.invalid/v1"\nwire_api="responses"\nenv_key="FIXTURE_CODEX_KEY"\n[hooks]\n[ mcp_servers.personal ]\ncommand="do-not-start"\n'
    )
    selected, env = codex_configuration()
    assert selected["model"] == "fixture-model"
    assert selected["model_providers.fixture.env_key"] == "FIXTURE_CODEX_KEY"
    assert env["FIXTURE_CODEX_KEY"] == "fixture-only-value"
    assert "fixture-only-value" not in str(selected)
    assert not any("hooks" in k or "mcp_servers" in k for k in selected)


async def issue_fixture(tmp_path):
    w, cfg, _, _, cycle = await setup(tmp_path, paired=False)
    w.discover()
    review = w.claim()
    seed_review_for_stage_fixture(w, review)
    f = {
        "mechanism": "context",
        "paths": [SOURCE],
        "case_id": "CODE-01",
        "fact": "PRIVATE-FACT-CANARY",
        "acceptance_metric": "tokens",
    }
    point = {"id": finding_id(f), "finding": f}
    w.save_report(
        review,
        {
            "cycle_id": cycle["cycle_id"],
            "day": w.day("owner"),
            "points": [point],
            "sha256": digest(point),
            "document": "Private complete review",
        },
    )
    w.complete(review, {"reviewed": 60})
    action = w.claim()
    assert action["kind"] == "issue"
    configure_publication(
        w.ledger.path.parent,
        "owner",
        {"repository": "example/rsi-test", "remote": "origin", "base": "main"},
    )
    return w, cfg, action


class GitHubFixture:
    def __init__(self, *, uncertain=False):
        self.issue, self.calls, self.uncertain = None, [], uncertain

    async def __call__(self, args, *, data=None, **kwargs):
        self.calls.append((args, data))
        if "search/issues" in args:
            return json.dumps({"items": [self.issue] if self.issue else []})
        if "POST" in args:
            if self.uncertain:
                raise OSError("transport result unknown")
            self.issue = {
                **json.loads(data),
                "id": 7,
                "number": 3,
                "html_url": "https://github.com/example/rsi-test/issues/3",
                "state": "open",
            }
        elif "PATCH" in args:
            self.issue.update(json.loads(data))
        return json.dumps(self.issue)


async def test_codex_issue_between_report_and_repair_is_single_idempotent_and_private(tmp_path):
    w, cfg, action = await issue_fixture(tmp_path)
    assert all(a["kind"] != "repair" for a in w.snapshot("owner")["actions"])
    with pytest.raises(DomainError, match="ISSUE_PUBLICATION_REQUIRED"):
        w.complete(action, {"executor_claims": "issue created"})
    gh = GitHubFixture()
    plan = await compose_issue(w, action, Settings(), cfg, provider_factory=lambda _: Reviewer())
    first = await publish_issue(w, action, plan, run=gh)
    again = await publish_issue(w, action, plan, run=gh)
    assert first == again and sum("POST" in args for args, _ in gh.calls) == 1
    assert "PRIVATE-FACT-CANARY" not in gh.issue["body"]
    assert "CODE-01" in gh.issue["body"] and "[ ]" in gh.issue["body"]
    w.complete(action, first)
    repair = w.claim()
    assert repair["kind"] == "repair" and repair["payload"]["issue"]["number"] == 3
    assert repair["payload"]["point_id"] == plan["points"][0]["id"]
    assert w.snapshot("other")["reports"] == []
    with pytest.raises(DomainError, match="REPORT_REQUIRED"):
        w.report("other", action["payload"]["cycle_id"])


async def test_unknown_issue_post_is_not_retried(tmp_path):
    w, cfg, action = await issue_fixture(tmp_path)
    plan = await compose_issue(w, action, Settings(), cfg, provider_factory=lambda _: Reviewer())
    gh = GitHubFixture(uncertain=True)
    with pytest.raises(OSError):
        await publish_issue(w, action, plan, run=gh)
    with pytest.raises(DomainError, match="OUTCOME_UNKNOWN"):
        await publish_issue(w, action, plan, run=gh)
    assert sum("POST" in args for args, _ in gh.calls) == 1
    assert not any(a["kind"] == "repair" for a in w.snapshot("owner")["actions"])


async def test_issue_checks_only_independently_closed_items_and_reopens_regression(tmp_path):
    w, cfg, action = await issue_fixture(tmp_path)
    plan = await compose_issue(w, action, Settings(), cfg, provider_factory=lambda _: Reviewer())
    gh = GitHubFixture()
    result = await publish_issue(w, action, plan, run=gh)
    w.complete(action, result, next_kind="sync_issue")
    sync = w.claim()
    assert sync["kind"] == "sync_issue"
    for state in ("observing", "closed_fixed", "reopened"):
        with w.ledger.connection() as db:
            db.execute("UPDATE rsi_improvements SET state=? WHERE owner=?", (state, "owner"))
        updated = await sync_issue(w, sync, run=gh)
        assert updated["state"] == ("closed" if state == "closed_fixed" else "open")
        assert ("[x]" in gh.issue["body"]) == (state == "closed_fixed")


async def test_all_sixty_reviews_produce_complete_document_before_issue_dispatch(tmp_path):
    w, cfg, _, _, cycle = await setup(tmp_path, paired=False)
    w.discover()
    action = w.claim()
    await observe_cycle(
        w, action, Settings(), cfg, provider_factory=lambda _: Reviewer(finding=True)
    )
    report = w.report("owner", cycle["cycle_id"])
    assert report["reviewer"] == "codex" and len(report["points"]) == 1
    assert "全量指标" in report["document"] and "MECH-PL01" in report["document"]
    assert not any(a["kind"] == "repair" for a in w.snapshot("owner")["actions"])
    w.complete(action, {"reviewed": 60})
    assert w.claim()["kind"] == "issue"


async def test_multiple_machines_wait_for_all_reviews_then_share_one_period_issue(tmp_path):
    w, cfg, _, _, first = await setup(tmp_path, paired=False)
    second = await run_cycle(
        ledger=w.ledger,
        owner="owner",
        day=w.day("owner"),
        suite=make_suite(),
        machine={**MACHINE, "id": "second"},
        executor=FixtureExecutor(),
        baseline={},
        candidate={},
        output_root=w.ledger.path.parent / "runs",
        daily_tokens=20000000,
        daily_episodes=1000,
        paired=False,
    )
    with w.ledger.connection() as db:
        for result in (first, second):
            row = db.execute(
                "SELECT manifest_json FROM rsi_cycles WHERE id=?", (result["cycle_id"],)
            ).fetchone()
            manifest = {
                **json.loads(row[0]),
                "schedule_period": "2026-10-24",
                "period_machines": ["fixture", "second"],
            }
            db.execute(
                "UPDATE rsi_cycles SET manifest_json=? WHERE id=?",
                (json.dumps(manifest), result["cycle_id"]),
            )
    w.discover()
    for i in range(2):
        review = w.claim()
        assert review["kind"] == "review"
        await observe_cycle(
            w, review, Settings(), cfg, provider_factory=lambda _: Reviewer(finding=True)
        )
        w.complete(review, {"reviewed": 60})
        if i == 0:
            assert not any(a["kind"] in {"issue", "repair"} for a in w.snapshot("owner")["actions"])
    action = w.claim()
    assert action["kind"] == "issue" and action["subject"].startswith("period-")
    report = w.report("owner", action["subject"])
    assert len(report["source_cycles"]) == 2 and len(report["points"]) == 1
    assert "## fixture" in report["document"] and "## second" in report["document"]
    assert sum(a["kind"] == "issue" for a in w.snapshot("owner")["actions"]) == 1


async def test_production_review_batches_cover_all_sixty_and_resume_without_extra_calls(
    tmp_path, monkeypatch
):
    w, cfg, _, _, cycle = await setup(tmp_path, paired=False)
    w.discover()
    action = w.claim()
    cached, batches = {}, []

    async def paid(workflow, action, settings, config, key, messages, **kwargs):
        if key in cached:
            return cached[key]
        if key.startswith("batch:"):
            trials = json.loads(messages[1]["content"])["trials"]
            assert 1 <= len(trials) <= 4
            assert len({p["protected"] for p in trials.values()}) == 1
            batches.append(set(trials))
            value = {
                "reviews": [
                    {"key": key, "reviewed": True, "reads": [], "findings": []} for key in trials
                ]
            }
        else:
            assert key == "period-report"
            value = {"summary": "Fixture batch report"}
        cached[key] = {"text": json.dumps(value)}
        return cached[key]

    monkeypatch.setattr("roami_agent.improvement.behavior_observer.model_json", paid)
    await observe_cycle(w, action, Settings(), cfg)
    assert len(batches) == 15 and len(cached) == 16
    assert len(set.union(*batches)) == 60
    saved = w.review_saved("owner", cycle["cycle_id"])
    key = next(iter(saved))
    with w.ledger.connection() as db:
        db.execute(
            "DELETE FROM rsi_semantic_reviews WHERE owner=? AND cycle_id=? AND trial_key=?",
            ("owner", cycle["cycle_id"], key),
        )
    await observe_cycle(w, action, Settings(), cfg)
    assert len(batches) == 15 and len(cached) == 16
    assert len(w.review_saved("owner", cycle["cycle_id"])) == 60


async def test_daily_schedule_is_idempotent_expires_old_jobs_and_respects_stop(
    tmp_path, monkeypatch
):
    from datetime import datetime

    class DailyClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 24, 3, 0, tzinfo=tz)

    monkeypatch.setattr("roami_agent.improvement.control.datetime", DailyClock)
    w, _, _, _, _ = await setup(tmp_path, paired=False)
    control = ImprovementControl(w.ledger)
    control.save("owner", {**control.preferences("owner"), "enabled": True})
    old = control.enqueue("owner", machine_id="fixture", request_key="2026-10-23", kind="daily")
    control.schedule()
    control.schedule()
    rows = control.requests("owner")
    assert len(rows) == 2
    assert next(r for r in rows if r["id"] == old["id"])["error_code"] == "RSI_SCHEDULE_EXPIRED"
    request = control.claim()
    assert control.profiles(request)[0]["period_key"] == "2026-10-24"
    control.finish(request, "interrupted")
    control.save("owner", {**control.preferences("owner"), "enabled": False})
    control.enqueue("owner", machine_id="fixture", request_key="2026-10-25", kind="daily")
    assert control.claim() is None
    manual = control.enqueue("owner", machine_id="fixture", request_key="explicit-manual")
    assert control.claim()["id"] == manual["id"]
