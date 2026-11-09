import json

import pytest
import test_swarm_delegations
from test_publication_approved_assets import prepared
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.publication.releases import PublicationReleases
from roami_agent.replies.source_review import SourceReplyReview
from roami_agent.storage.database import row

coordination = coordination_fixture
delegated_team = delegated_team_fixture
AUTO = "Main每日独立审核本项目X与B站，通过后自动发布、取数与复盘，不逐条报批。"


@pytest.fixture(autouse=True)
def automatic_goal(monkeypatch):
    monkeypatch.setattr(test_swarm_delegations, "GOAL", AUTO)


async def release_fixture(coordination):
    runtime, binding, scope, frozen, review = await prepared(coordination)

    class PolicyModel:
        model = "isolated-release-policy"
        settings_hash = "fixture-settings"

        async def stream(self, messages, tools):
            assert json.loads(messages[1]["content"])["goalUserMessage"]["text"] == AUTO
            yield ModelEvent(
                "tool",
                {
                    "id": "policy",
                    "type": "function",
                    "function": {
                        "name": "source_review_verdict",
                        "arguments": '{"accepted":true,"feedback":"isolated semantic verdict"}',
                    },
                },
            )

    reviewer = SourceReplyReview(runtime.db, lambda: model)
    model = PolicyModel()
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c "
            "ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    plan, prompt = await runtime.loop.context.build(turn, "Review publication mode.", [], None)
    reviewer.observe_context(turn, prompt, source_ids=plan["modelSourceMessageIds"])
    service = PublicationReleases(runtime.db, runtime.artifacts, reviewer)
    args = (binding, scope, frozen["versionId"], review["reviewId"], "x", "12345")
    return runtime, service, args


async def test_release_retries_reuse_approved_bytes_without_granting_send_rights(coordination):
    runtime, service, args = await release_fixture(coordination)
    first = await service.prepare(*args)
    assert await service.prepare(*args) == first
    assert first["publicationAuthorized"] is False
    assert (
        await runtime.db.call(lambda db: service.read(db, "alice", "project-a", first["releaseId"]))
        == first
    )


@pytest.mark.parametrize("fault", [None, "projectId", "memberId", "taskId", "accountId"])
async def test_original_main_can_create_release_through_registered_cli(coordination, fault):
    runtime, service, args = await release_fixture(coordination)
    binding, scope, version_id, review_id, channel, account = args
    runtime.reply_review = service.reviewer
    parameters = {
        key: scope[key] for key in ("projectId", "swarmId", "delegationId", "memberId", "taskId")
    }
    parameters.update(versionId=version_id, reviewId=review_id, channel=channel, accountId=account)
    if fault:
        parameters[fault] = "99999" if fault == "accountId" else "other"
    wire = {
        "function": {
            "name": "bash",
            "arguments": json.dumps(
                {
                    "argv": [
                        "roami",
                        "swarm",
                        "publication",
                        "release",
                        "--input",
                        json.dumps(parameters),
                    ]
                }
            ),
        }
    }
    if fault:
        with pytest.raises(DomainError):
            await runtime.tools.invoke(wire, "main", {**binding, "toolCallId": "release-cli"})
    else:
        result = await runtime.tools.invoke(wire, "main", {**binding, "toolCallId": "release-cli"})
        assert result["kind"] == "publication_release"
        assert result["publicationAuthorized"] is False
        assert result["scope"]["taskId"] == scope["taskId"]


@pytest.mark.parametrize("owner,project", [("bob", "project-a"), ("alice", "project-b")])
async def test_release_cannot_be_read_through_another_owner_or_project(
    coordination, owner, project
):
    runtime, service, args = await release_fixture(coordination)
    release = await service.prepare(*args)
    with pytest.raises(DomainError, match="PUBLICATION_RELEASE_NOT_FOUND"):
        await runtime.db.call(lambda db: service.read(db, owner, project, release["releaseId"]))


async def test_release_rechecks_deleted_asset_after_physical_read(coordination, monkeypatch):
    runtime, service, args = await release_fixture(coordination)
    original = runtime.artifacts.verified_path

    async def deleted_after_read(owner, artifact_id):
        path = await original(owner, artifact_id)
        await runtime.artifacts.delete(owner, artifact_id)
        return path

    monkeypatch.setattr(runtime.artifacts, "verified_path", deleted_after_read)
    with pytest.raises(DomainError, match="PUBLICATION_ARTIFACT_UNAVAILABLE"):
        await service.prepare(*args)
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM swarm_commands WHERE command_key LIKE 'publication-release:%'"
            ).fetchone()[0]
        )
        == 0
    )


async def running_release(coordination, tmp_path):
    from test_swarm_delegations import finish

    runtime, service, args = await release_fixture(coordination)
    binding, scope = args[:2]
    release = await service.prepare(*args)
    folder = tmp_path / "project"
    folder.mkdir()

    async def workspace(project):
        assert project == "project-a"
        return {"projectId": project, "directory": str(folder)}

    runtime.tasks.revisions.project_workspace = workspace
    await runtime.db.call(
        lambda db: (
            db.execute(
                "UPDATE task_attempts SET session_id='original-session',agent_conversation_id='provider-original' WHERE id=?",
                (scope["runId"],),
            ),
            db.execute(
                "UPDATE tasks SET target_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "sessionId": "original-session",
                            "workdir": str(folder),
                            "workspace": {"directory": str(folder)},
                        }
                    ),
                    scope["taskId"],
                ),
            ),
        ),
        write=True,
    )
    requested = await runtime.tasks.revisions.request(
        "alice",
        scope["taskId"],
        "继续原实例，执行已审核内容的发布与回执核对。",
        1,
        "publication-next-round",
        source_turn_id=binding["turnId"],
        source_conversation_id=binding["conversation"],
        source_lease_epoch=binding["leaseEpoch"],
    )
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    await finish(runtime, turn)
    await runtime.tasks.revisions.advance()
    job = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (requested["operationId"],))
    )
    applied = json.loads(job["payload_json"])
    actor = {
        "owner": "alice",
        "role": "worker",
        "taskId": scope["taskId"],
        "runId": applied["runId"],
    }

    class WaitingExecutor:
        async def run(self, task, run):
            assert run["id"] == actor["runId"]

    runtime.dispatch.executor = WaitingExecutor()
    dispatch = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.run' AND json_extract(payload_json,'$.runId')=?",
            (actor["runId"],),
        )
    )
    await runtime.dispatch.run(dispatch)
    return runtime, service, release, actor


def resource_proof(db, binding, release, execution):
    return {
        **execution,
        "channel": release["channel"],
        "accountId": release["accountId"],
        "resourceId": "fixture-resource",
        "routeId": "fixture-native-skill",
        "routeProofId": "fixture-host-account-proof",
    }


async def test_applied_original_run_can_reserve_only_one_submission(coordination, tmp_path):
    from roami_agent.publication.post_journal import PostJournal

    runtime, service, release, actor = await running_release(coordination, tmp_path)
    journal = PostJournal(
        runtime.db,
        lambda db, binding, release_id: service.admit(
            db, binding, "project-a", release_id, resource_proof
        ),
    )
    attempt = await journal.reserve(actor, release["releaseId"])
    assert attempt["context"]["revision"] == 2
    assert attempt["context"]["operationId"]
    assert await journal.reserve(actor, release["releaseId"]) == attempt
    event = {key: attempt["context"][key] for key in ("businessKey", "accountId", "versionSha256")}
    event.update(phase="post_submit", requestSha256="a" * 64, media=[])
    await journal.record(actor, attempt, event)
    with pytest.raises(DomainError, match="PUBLICATION_RECONCILIATION_REQUIRED"):
        await journal.record(actor, attempt, event)


@pytest.mark.parametrize(
    "fault", ["old_run", "revoked", "wrong_account", "missing_adapter", "main_role"]
)
async def test_release_admission_rechecks_execution_and_host_resource(
    coordination, tmp_path, fault
):
    runtime, service, release, actor = await running_release(coordination, tmp_path)
    route = resource_proof
    if fault == "main_role":
        actor["role"] = "main"
    elif fault == "old_run":
        actor["runId"] = await runtime.db.call(
            lambda db: db.execute(
                "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=1",
                (actor["taskId"],),
            ).fetchone()[0]
        )
    elif fault == "revoked":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id WHERE id=?",
                (release["scope"]["delegationId"],),
            ),
            write=True,
        )
    elif fault == "wrong_account":

        def route(db, binding, release, execution):
            return {**resource_proof(db, binding, release, execution), "accountId": "999"}
    else:
        route = None
    with pytest.raises(DomainError):
        await runtime.db.call(
            lambda db: service.admit(db, actor, "project-a", release["releaseId"], route)
        )


async def browser_release(coordination, tmp_path):
    from roami_agent.publication.browser_admission import BrowserPublicationAdmission

    runtime, service, release, actor = await running_release(coordination, tmp_path)
    resource = await runtime.resources.claim(
        "alice", actor["taskId"], actor["runId"], "browser", "browser:fixture:target:publication"
    )
    observed = await runtime.resources.observe(
        "alice",
        resource["id"],
        actor["taskId"],
        actor["runId"],
        resource["lease_epoch"],
        "b" * 64,
        {"url": "https://x.com/compose/post"},
    )
    account = {
        "kind": "publication_account_identity",
        "proofId": "isolated-host-probe",
        "accountId": "12345",
        "channel": "x",
        "resourceId": resource["id"],
        "observationId": observed["id"],
        "leaseEpoch": resource["lease_epoch"],
        "sceneEpoch": observed["sceneEpoch"],
        "signature": observed["signature"],
    }
    route = BrowserPublicationAdmission(
        runtime.resources, resource["id"], "fixture-skill", "c" * 64, lambda *args: account
    )
    return runtime, service, release, actor, resource, observed, route


async def test_browser_release_uses_current_owned_resource_and_host_probe(coordination, tmp_path):
    runtime, service, release, actor, resource, _, route = await browser_release(
        coordination, tmp_path
    )
    context = await runtime.db.call(
        lambda db: service.admit(db, actor, "project-a", release["releaseId"], route)
    )
    assert context["resourceId"] == resource["id"] and len(context["routeProofId"]) == 64
    assert context["runId"] == actor["runId"]


@pytest.mark.parametrize(
    "fault",
    ["takeover", "expired", "new_observation", "wrong_platform", "pending_action", "missing_probe"],
)
async def test_browser_release_refuses_stale_or_unverified_resource(coordination, tmp_path, fault):
    runtime, service, release, actor, resource, observed, route = await browser_release(
        coordination, tmp_path
    )
    if fault == "takeover":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE resources SET state='paused' WHERE id=?", (resource["id"],)
            ),
            write=True,
        )
    elif fault == "expired":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE resources SET lease_until_ms=1 WHERE id=?", (resource["id"],)
            ),
            write=True,
        )
    elif fault in {"new_observation", "wrong_platform"}:
        url = (
            "https://x.com/compose/post"
            if fault == "new_observation"
            else "https://x.com.example.org/compose/post"
        )
        await runtime.resources.observe(
            "alice",
            resource["id"],
            actor["taskId"],
            actor["runId"],
            resource["lease_epoch"],
            "d" * 64,
            {"url": url},
        )
    elif fault == "pending_action":
        await runtime.resources.begin(
            "alice",
            resource["id"],
            actor["taskId"],
            actor["runId"],
            resource["lease_epoch"],
            observed["id"],
            observed["sceneEpoch"],
            {"kind": "click", "selector": "#submit"},
            "isolated-pending-action",
        )
    else:
        route.account_admission = None
    with pytest.raises(DomainError):
        await runtime.db.call(
            lambda db: service.admit(db, actor, "project-a", release["releaseId"], route)
        )
