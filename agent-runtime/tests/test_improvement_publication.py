"""Publication retries reconcile a fixed draft; unverified and unknown writes stay fenced."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roami_agent.improvement.github_publication import (
    configure_publication,
    profile_path,
    publication_profile,
    publish_verified,
)
from roami_agent.improvement.ledger import Ledger
from roami_agent.improvement.source_revision import git
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


async def fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    await git(repo, "init", "-q")
    await git(repo, "remote", "add", "origin", "https://github.com/example/rsi-test.git")
    ledger = Ledger(tmp_path / "private/ledger.sqlite3")
    workflow = SimpleNamespace(ledger=ledger, _owned_action=lambda db, action: None)
    configure_publication(
        ledger.path.parent,
        "owner",
        {"repository": "example/rsi-test", "remote": "origin", "base": "main"},
    )
    candidate = {
        "verified_by": "host_code_verifier_v1",
        "comparison": {"eligible_for_promotion": True},
        "candidate_root": str(repo),
        "candidate_build_hash": "b" * 64,
        "baseline_build_hash": "d" * 64,
        "verification_cycles": ["formal", "private"],
        "improvement_id": "item",
        "finding": {"case_id": "CODE-01", "fact": "private source fact must not be posted"},
        "paths": ["agent-runtime/src/roami_agent/context/example.py"],
        "regression_output_hash": "c" * 64,
    }

    class Revisions:
        async def seal(self, value):
            return {**value, "commit": "a" * 40}

    action = {"owner": "owner", "payload": candidate}
    calls = []
    remote = {"pull": None, "unknown": False}

    async def run(argv, *, data=None, timeout=60):
        calls.append((argv, data))
        if argv[0] == "git" and "get-url" in argv:
            return "https://github.com/example/rsi-test.git\n"
        if argv[:3] == ["gh", "api", "--method"]:
            method = argv[3]
            if method == "GET":
                return json.dumps([remote["pull"]] if remote["pull"] else [])
            if method == "POST":
                value = json.loads(data)
                remote["pull"] = {
                    "state": "open",
                    "draft": True,
                    "number": 1,
                    "html_url": "https://github.com/example/rsi-test/pull/1",
                    "head": {"sha": "a" * 40},
                    "base": {"ref": "main"},
                }
                assert value["draft"] is True and "private source fact" not in value["body"]
                if remote["unknown"]:
                    raise DomainError("NETWORK_RESPONSE_UNKNOWN")
                return json.dumps(remote["pull"])
            return "{}"
        if len(argv) > 2 and argv[1:3] == ["chrome", "screenshot"]:
            Path(argv[3]).write_bytes(b"\x89PNG\r\n\x1a\nfixture-only")
        return ""

    return workflow, action, Revisions(), {"repo": str(repo)}, calls, remote, run


async def test_verified_publication_runs_quality_and_creates_one_draft_with_evidence(tmp_path):
    w, a, revisions, cfg, calls, _remote, run = await fixture(tmp_path)
    first = await publish_verified(
        w, a, revisions, cfg, Settings(), run=run, validate=lambda *args: a["payload"]["comparison"]
    )
    assert first["review_publication"]["draft"] is True
    assert any("quick" in argv for argv, _ in calls)
    assert any(any(arg.endswith("/scripts/dev/pr-shot.sh") for arg in argv) for argv, _ in calls)
    again = await publish_verified(
        w, a, revisions, cfg, Settings(), run=run, validate=lambda *args: a["payload"]["comparison"]
    )
    assert again["review_publication"] == first["review_publication"]
    assert sum(argv[:4] == ["gh", "api", "--method", "POST"] for argv, _ in calls) == 1
    assert not any("--force" in argv for argv, _ in calls)


@pytest.mark.parametrize("found", [True, False])
async def test_unknown_create_is_reconciled_and_never_blindly_posted_again(tmp_path, found):
    w, a, revisions, cfg, calls, remote, run = await fixture(tmp_path)
    remote["unknown"] = True
    with pytest.raises(DomainError, match="NETWORK_RESPONSE_UNKNOWN"):
        await publish_verified(
            w,
            a,
            revisions,
            cfg,
            Settings(),
            run=run,
            validate=lambda *args: a["payload"]["comparison"],
        )
    if not found:
        remote["pull"] = None
    if found:
        result = await publish_verified(
            w,
            a,
            revisions,
            cfg,
            Settings(),
            run=run,
            validate=lambda *args: a["payload"]["comparison"],
        )
        assert result["review_publication"]["number"] == 1
    else:
        with pytest.raises(DomainError, match="RSI_PUBLICATION_OUTCOME_UNKNOWN"):
            await publish_verified(
                w,
                a,
                revisions,
                cfg,
                Settings(),
                run=run,
                validate=lambda *args: a["payload"]["comparison"],
            )
    assert sum(argv[:4] == ["gh", "api", "--method", "POST"] for argv, _ in calls) == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ("unverified", "RSI_VERIFICATION_REQUIRED"),
        ("rejected", "RSI_PROMOTION_REJECTED"),
        ("remote", "RSI_PUBLICATION_REMOTE_CONFLICT"),
        ("lease", "RSI_ACTION_LEASE_LOST"),
    ],
)
async def test_publication_guards_precede_external_writes(tmp_path, change, code):
    w, a, revisions, cfg, calls, _remote, run = await fixture(tmp_path)
    if change == "unverified":
        a["payload"]["verified_by"] = "executor-claim"
    if change == "rejected":
        a["payload"]["comparison"]["eligible_for_promotion"] = False
    if change == "remote":
        await git(
            Path(cfg["repo"]), "remote", "set-url", "origin", "https://github.com/other/repo.git"
        )
    if change == "lease":

        def revoked(db, action):
            raise DomainError("RSI_ACTION_LEASE_LOST")

        w._owned_action = revoked
    with pytest.raises(DomainError, match=code):
        await publish_verified(
            w,
            a,
            revisions,
            cfg,
            Settings(),
            run=run,
            validate=lambda *args: a["payload"]["comparison"],
        )
    assert not calls


def test_publication_profiles_are_private_validated_and_disabled_by_absence(tmp_path):
    assert publication_profile(tmp_path, "owner") is None
    with pytest.raises(DomainError):
        configure_publication(
            tmp_path, "owner", {"repository": None, "remote": "origin", "base": "main"}
        )
    assert not profile_path(tmp_path, "owner").exists()
    configure_publication(
        tmp_path, "owner", {"repository": "example/repo", "remote": "origin", "base": "main"}
    )
    profile_path(tmp_path, "owner").chmod(0o644)
    with pytest.raises(DomainError, match="PRIVATE"):
        publication_profile(tmp_path, "owner")


async def test_review_link_survives_in_owner_improvement_snapshot(tmp_path):
    from roami_agent.improvement.workflow import ResearchWorkflow

    ledger = Ledger(tmp_path / "ledger.sqlite3")
    url = "https://github.com/example/rsi-test/pull/1"
    with ledger.connection() as db:
        db.execute(
            "INSERT INTO rsi_improvements VALUES('item','owner','fp','ready',1,?,?,0)",
            (
                json.dumps({"fact": "Observed behavior"}),
                json.dumps({"review_publication": {"url": url}}),
            ),
        )
    assert ResearchWorkflow(ledger).snapshot("owner")["improvements"][0]["reviewUrl"] == url
    assert ResearchWorkflow(ledger).snapshot("other")["improvements"] == []


async def test_worker_hands_verified_result_to_publication_and_waits_on_failure(tmp_path):
    from test_improvement_workflow import (
        SOURCE,
        complete_review_fixture,
        seed_review_for_stage_fixture,
        setup,
    )

    from roami_agent.improvement.research_worker import ResearchWorker

    workflow, _config, _clock, _repo, _cycle = await setup(tmp_path)
    workflow.discover()
    review = workflow.claim()
    seed_review_for_stage_fixture(workflow, review)
    finding = {
        "case_id": "CODE-01",
        "mechanism": "context-retention",
        "fact": "Fixture evidence",
        "paths": [SOURCE],
    }
    workflow.record_findings(review, [finding])
    complete_review_fixture(workflow, review, {"fixture_only": True})
    repair = workflow.claim()
    candidate = {
        "improvement_id": repair["payload"]["improvement_id"],
        "finding": finding,
        "fixture_only": True,
    }
    workflow.complete(repair, candidate, next_kind="verify", item_state="verifying")
    configure_publication(
        workflow.ledger.path.parent,
        "owner",
        {"repository": "example/repo", "remote": "origin", "base": "main"},
    )

    async def verified(action, config):
        return candidate

    async def unavailable(action, config):
        raise DomainError("RSI_PUBLICATION_COMMAND_FAILED")

    worker = ResearchWorker(
        SimpleNamespace(settings=SimpleNamespace(current=Settings())),
        SimpleNamespace(ledger=workflow.ledger, research=workflow),
        handlers={"verify": verified, "publish": unavailable},
    )
    await worker.execute(workflow.claim())
    publish = workflow.claim()
    assert publish["kind"] == "publish"
    await worker.execute(publish)
    assert workflow.claim() is None
    snapshot = workflow.snapshot("owner")
    assert snapshot["improvements"][0]["state"] == "blocked"
    assert not any(action["kind"] == "activate" for action in snapshot["actions"])
