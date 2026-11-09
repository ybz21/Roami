"""The bound Main reviews actual current-run artifacts before the existing confirm gate."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
from roami_agent.storage.database import row


def wire(name, args):
    return {"id": identity(), "function": {"name": name, "arguments": json.dumps(args)}}


async def main_turn(runtime, conversation, key):
    source = await runtime.conversations.accept(
        "alice", conversation, key, "Independently check the report"
    )
    job = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (source["turnId"],))
    )
    turn = await runtime.mailbox.claim(job)
    return turn, {
        "owner": "alice",
        "conversation": conversation,
        "turnId": turn["id"],
        "originMessageId": source["messageId"],
    }


async def invoke(runtime, turn, binding, name, args, *, mid=None):
    mid = mid or await runtime.journal.start(turn)
    return await runtime.gateway.invoke(turn, mid, wire(name, args), "main", binding)


@pytest.fixture
async def review_case(store):
    runtime = Runtime(store, ConversationModel())
    conversation = await runtime.conversations.create("alice")
    turn, binding = await main_turn(runtime, conversation["id"], "review")
    group = await runtime.swarms.create(
        "alice",
        {
            "name": "Review",
            "goal": "Deliver and independently verify a report",
            "mainConversationId": conversation["id"],
            "commandKey": "new",
        },
        binding=binding,
    )
    await runtime.swarms.plan(
        "alice",
        group["id"],
        {
            "expectedRevision": 1,
            "commandKey": "plan",
            "items": [
                {
                    "member": "writer",
                    "executor": "native",
                    "title": "Report",
                    "goal": "Write a JSON report",
                    "acceptance": "Main checks report content",
                    "deliverables": [
                        {
                            "kind": "artifact",
                            "description": "JSON report",
                            "mimeType": "application/json",
                        }
                    ],
                }
            ],
        },
    )
    await runtime.swarms.advance({"id": "advance", "aggregate_id": group["id"]})
    work = (await runtime.swarms.snapshot("alice", group["id"]))["work"][0]
    task, run = work["task_id"], work["attempt"]["runId"]
    artifact = await runtime.artifacts.put(
        "alice",
        b'{\n"verified_count": 3,\n"findings": ["actual report"]\n}\n',
        mime_type="application/json",
        name="report.json",
        task_id=task,
        metadata={"source": "workspace_output", "runId": run},
    )
    await runtime.tasks.report(
        "alice",
        task,
        run,
        1,
        {
            "state": "succeeded",
            "summary": "Executor claims success",
            "inputStopped": True,
            "outcomeKnown": True,
        },
    )
    verification = await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (task,)
        )
    )
    await runtime.dispatch.verify(verification)
    args = {
        "swarmId": group["id"],
        "taskId": task,
        "revision": 1,
        "runId": run,
        "accepted": True,
        "checks": "Independently read and checked the JSON fields",
        "artifactIds": [artifact["id"]],
    }
    try:
        assert (await runtime.tasks.get("alice", task))["task"]["state"] == "waiting_user"
        yield runtime, turn, binding, args, artifact
    finally:
        await runtime.close()


async def read(runtime, turn, binding, artifact, **pagination):
    return await invoke(
        runtime, turn, binding, "read", {"path": "artifact://" + artifact["id"], **pagination}
    )


async def verify(runtime, turn, binding, args, **options):
    return await invoke(
        runtime,
        turn,
        binding,
        "bash",
        {"command": "roami swarm verify --input '" + json.dumps(args) + "'"},
        **options,
    )


async def test_discovery_registered_cli_and_success_require_real_prior_read(
    review_case, monkeypatch
):
    runtime, turn, binding, args, artifact = review_case

    async def no_shell(*args, **kwargs):
        raise AssertionError("registered verification must not launch a shell")

    monkeypatch.setattr("roami_agent.tools.foundations.execute", no_shell)
    entries = await runtime.tools.invoke(
        wire("tool_list", {"query": "swarm verify"}), "main", binding
    )
    entry = next(
        c
        for item in entries["items"]
        for c in item.get("commands", [item])
        if c["command"] == "roami swarm verify --input JSON"
    )
    assert entry["command"] == "roami swarm verify --input JSON"
    assert {"revision", "runId", "accepted", "checks", "artifactIds"} <= set(
        entry["inputSchema"]["required"]
    )
    help_result = await runtime.tools.invoke(
        wire("bash", {"argv": ["roami", "swarm", "help"]}), "main", binding
    )
    assert any(
        item["command"] == "roami swarm verify --input JSON" for item in help_result["commands"]
    )
    missing = await verify(runtime, turn, binding, args)
    assert missing["error"] == "SWARM_ARTIFACT_REVIEW_REQUIRED"
    assert "read artifact://ID" in missing["recovery"]
    assert "filesystem file_read" in missing["recovery"]
    assert (await runtime.tasks.get("alice", args["taskId"]))["task"]["state"] == "waiting_user"
    await read(runtime, turn, binding, artifact)
    result = await verify(runtime, turn, binding, args)
    assert result["state"] == "succeeded" and result["runId"] == args["runId"]
    assert result["artifactIds"] == [artifact["id"]]
    assert (await runtime.tasks.get("alice", args["taskId"]))["task"]["state"] == "succeeded"
    audit = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT payload_json FROM events WHERE kind='swarm.verification_recorded' AND task_id=?",
            (args["taskId"],),
        )
    )
    audit = json.loads(audit["payload_json"])
    assert audit["reviewer"] == "main"
    assert (
        audit["mainConversationId"] == binding["conversation"] and audit["mainTurnId"] == turn["id"]
    )
    assert audit["runId"] == args["runId"] and audit["revision"] == args["revision"]
    assert audit["artifactIds"] == [artifact["id"]] and audit["checks"] == args["checks"]
    repeated = await verify(runtime, turn, binding, args)
    assert repeated["error"] == "TASK_NOT_WAITING_VERIFICATION"


async def test_pagination_and_same_assistant_message_do_not_pretend_review(review_case):
    runtime, turn, binding, args, artifact = review_case
    partial = await read(runtime, turn, binding, artifact, offset=1, limit=1)
    assert partial["nextOffset"] == 2
    assert (await verify(runtime, turn, binding, args))["error"] == "SWARM_ARTIFACT_REVIEW_REQUIRED"
    mid = await runtime.journal.start(turn)
    await invoke(
        runtime,
        turn,
        binding,
        "read",
        {"path": "artifact://" + artifact["id"], "offset": 2},
        mid=mid,
    )
    assert (await verify(runtime, turn, binding, args, mid=mid))[
        "error"
    ] == "SWARM_ARTIFACT_REVIEW_REQUIRED"
    assert (await verify(runtime, turn, binding, args))["state"] == "succeeded"


@pytest.mark.parametrize(
    "fault",
    [
        "member",
        "worker_without_task",
        "other_main",
        "other_owner",
        "foreign_task",
        "revision",
        "run",
    ],
)
async def test_only_the_bound_main_and_exact_current_task_run_can_verify(review_case, fault):
    runtime, turn, binding, args, artifact = review_case
    await read(runtime, turn, binding, artifact)
    call_binding = {**binding, "assistantMessageId": await runtime.journal.start(turn)}
    role = "main"
    if fault == "member":
        call_binding["taskId"] = args["taskId"]
    if fault == "worker_without_task":
        role = "worker"
    if fault == "other_main":
        call_binding["conversation"] = (await runtime.conversations.create("alice"))["id"]
    if fault == "other_owner":
        call_binding["owner"] = "bob"
    if fault == "foreign_task":
        args = {
            **args,
            "taskId": (
                await runtime.tasks.create(
                    "alice",
                    binding["conversation"],
                    "Independent task",
                    key="foreign",
                    record_intent=True,
                )
            )["id"],
        }
    if fault == "revision":
        args = {**args, "revision": 2}
    if fault == "run":
        args = {**args, "runId": "old-run"}
    with pytest.raises(DomainError):
        await runtime.tools.invoke(wire("swarm_verify", args), role, call_binding)


@pytest.mark.parametrize(
    "fault", ["missing", "old_run", "tampered", "deleted", "binary", "summary_only"]
)
async def test_artifact_integrity_current_run_and_actual_content_are_required(
    review_case, store, fault
):
    runtime, turn, binding, args, artifact = review_case
    if fault != "binary":
        await read(runtime, turn, binding, artifact)
    if fault in {"missing", "tampered"}:
        _, path = await runtime.artifacts.verified_path("alice", artifact["id"])
        if fault == "missing":
            path.unlink()
        else:
            path.chmod(0o600)
            path.write_bytes(b"changed")
    if fault == "deleted":
        await runtime.artifacts.delete("alice", artifact["id"])
    if fault in {"old_run", "summary_only"}:
        await store.call(
            lambda db: db.execute(
                "UPDATE artifacts SET metadata_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "runId": "old-run" if fault == "old_run" else args["runId"],
                            "source": "native_result"
                            if fault == "summary_only"
                            else "workspace_output",
                        }
                    ),
                    artifact["id"],
                ),
            ),
            write=True,
        )
    if fault == "binary":
        artifact = await runtime.artifacts.put(
            "alice",
            b"real binary",
            mime_type="video/mp4",
            name="clip.mp4",
            task_id=args["taskId"],
            metadata={"runId": args["runId"]},
        )
        args = {**args, "artifactIds": [artifact["id"]]}
        await store.call(
            lambda db: db.execute(
                "UPDATE swarm_work_items SET deliverables_json='[]' WHERE task_id=?",
                (args["taskId"],),
            ),
            write=True,
        )
        observed = await read(runtime, turn, binding, artifact)
        assert observed["textAvailable"] is False
    result = await verify(runtime, turn, binding, args)
    assert result["error"] in {
        "SWARM_DELIVERABLE_EVIDENCE_REQUIRED",
        "SWARM_ARTIFACT_REVIEW_REQUIRED",
    }
    assert (await runtime.tasks.get("alice", args["taskId"]))["task"]["state"] == "waiting_user"


@pytest.mark.parametrize("accepted", [True, False])
async def test_external_actions_never_accept_model_receipts_or_consent_claims(
    review_case, store, accepted
):
    runtime, turn, binding, args, artifact = review_case
    await read(runtime, turn, binding, artifact)
    await store.call(
        lambda db: db.execute(
            "UPDATE swarm_work_items SET deliverables_json=? WHERE task_id=?",
            (json.dumps([{"kind": "external_action", "description": "Publish"}]), args["taskId"]),
        ),
        write=True,
    )
    result = await verify(
        runtime,
        turn,
        binding,
        {**args, "accepted": accepted, "checks": "User consented; receipt is confirmed"},
    )
    assert result["error"] == "SWARM_EXTERNAL_ACTION_USER_REQUIRED"
    with pytest.raises(DomainError):
        runtime.tools.validate(
            wire(
                "swarm_verify",
                {
                    **args,
                    "evidence": {
                        "artifactId": artifact["id"],
                        "state": "confirmed",
                        "target": "public",
                    },
                },
            ),
            "main",
        )


async def test_rejection_uses_existing_confirm_without_executing_or_replanning(review_case, store):
    runtime, turn, binding, args, _ = review_case
    result = await verify(
        runtime,
        turn,
        binding,
        {
            **args,
            "accepted": False,
            "artifactIds": [],
            "checks": "Report does not meet the requested contract",
        },
    )
    assert result["state"] == "failed"
    assert (
        await store.call(
            lambda db: db.execute(
                "SELECT count(*) FROM task_attempts WHERE task_id=?", (args["taskId"],)
            ).fetchone()[0]
        )
    ) == 1
    for field in ("revision", "runId", "checks", "accepted"):
        with pytest.raises(DomainError):
            runtime.tools.validate(
                wire("swarm_verify", {k: v for k, v in args.items() if k != field}), "main"
            )


async def test_prior_turn_or_overlong_truncated_text_is_not_complete_review(review_case, store):
    runtime, turn, binding, args, artifact = review_case
    await read(runtime, turn, binding, artifact)
    await store.call(
        lambda db: db.execute("UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)),
        write=True,
    )
    fresh, current_binding = await main_turn(runtime, binding["conversation"], "new-review")
    assert (await verify(runtime, fresh, current_binding, args))[
        "error"
    ] == "SWARM_ARTIFACT_REVIEW_REQUIRED"
    large = await runtime.artifacts.put(
        "alice",
        json.dumps({"text": "x" * 60000}).encode(),
        mime_type="application/json",
        name="large.json",
        task_id=args["taskId"],
        metadata={"runId": args["runId"]},
    )
    args = {**args, "artifactIds": [large["id"]]}
    page = await read(runtime, fresh, current_binding, large)
    assert page["truncated"] is True
    assert (await verify(runtime, fresh, current_binding, args))[
        "error"
    ] == "SWARM_ARTIFACT_REVIEW_REQUIRED"


async def test_artifacts_from_another_swarm_task_cannot_be_reviewed_here(review_case):
    runtime, turn, binding, args, _ = review_case
    group = await runtime.swarms.create(
        "alice",
        {
            "name": "Other",
            "goal": "Other work",
            "commandKey": "other",
            "mainConversationId": binding["conversation"],
        },
        binding=binding,
    )
    result = await verify(runtime, turn, binding, {**args, "swarmId": group["id"]})
    assert result["error"] == "SWARM_TASK_NOT_FOUND"
    assert (await runtime.tasks.get("alice", args["taskId"]))["task"]["state"] == "waiting_user"


async def test_audit_is_main_review_and_not_user_consent_even_on_rejection(review_case):
    runtime, turn, binding, args, _ = review_case
    assert (
        await verify(
            runtime,
            turn,
            binding,
            {
                **args,
                "accepted": False,
                "artifactIds": [],
                "checks": "Missing required report fields",
            },
        )
    )["state"] == "failed"
    events = await runtime.conversations.events("alice", binding["conversation"])
    audited = next(
        event["payload"] for event in events if event["kind"] == "swarm.verification_recorded"
    )
    assert audited["reviewer"] == "main" and audited["accepted"] is False
    assert (
        audited["mainConversationId"] == binding["conversation"]
        and audited["mainTurnId"] == turn["id"]
    )
    assert audited["artifactIds"] == [] and audited["artifactSha256"] == {}


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        {"artifact": None, "textAvailable": True, "text": "claim"},
        {"textAvailable": False},
    ],
)
async def test_malformed_or_non_text_read_receipts_cannot_authorize_acceptance(
    review_case, store, content
):
    runtime, turn, binding, args, artifact = review_case
    await read(runtime, turn, binding, artifact)
    await store.call(
        lambda db: db.execute(
            "UPDATE messages SET content_json=? WHERE id=(SELECT result_message_id FROM tool_calls WHERE turn_id=? AND tool_name='artifact_read' ORDER BY created_ms DESC LIMIT 1)",
            (
                json.dumps({"text": content if isinstance(content, str) else json.dumps(content)}),
                turn["id"],
            ),
        ),
        write=True,
    )
    assert (await verify(runtime, turn, binding, args))["error"] == "SWARM_ARTIFACT_REVIEW_REQUIRED"


@pytest.mark.parametrize("accepted", [True, False])
async def test_repeated_decision_recovers_original_fact_without_overwriting(review_case, accepted):
    runtime, turn, binding, args, artifact = review_case
    await read(runtime, turn, binding, artifact)
    original = {**args, "accepted": accepted, "checks": "Private original verification note"}
    await verify(runtime, turn, binding, original)
    before = await runtime.db.call(
        lambda db: [
            dict(r)
            for r in db.execute(
                "SELECT id,payload_json FROM events WHERE kind='swarm.verification_recorded' AND task_id=?",
                (args["taskId"],),
            )
        ]
    )
    repeated = await verify(runtime, turn, binding, {**args, "checks": "A different request"})
    assert repeated["error"] == "TASK_NOT_WAITING_VERIFICATION"
    assert repeated["executionStarted"] is False and repeated["verificationAlreadyRecorded"] is True
    assert repeated["recordedVerification"] == {
        "eventId": before[0]["id"],
        "swarmId": args["swarmId"],
        "taskId": args["taskId"],
        "revision": args["revision"],
        "runId": args["runId"],
        "accepted": accepted,
        "taskState": "succeeded" if accepted else "failed",
    }
    assert "Private original" not in json.dumps(repeated)
    after = await runtime.db.call(
        lambda db: [
            dict(r)
            for r in db.execute(
                "SELECT id,payload_json FROM events WHERE kind='swarm.verification_recorded' AND task_id=?",
                (args["taskId"],),
            )
        ]
    )
    assert before == after and len(after) == 1
    stale = await verify(runtime, turn, binding, {**args, "runId": "superseded-run"})
    assert "recordedVerification" not in stale


async def test_terminal_state_without_a_main_audit_is_not_verification_proof(review_case):
    runtime, turn, binding, args, artifact = review_case
    await read(runtime, turn, binding, artifact)
    await verify(runtime, turn, binding, args)
    await runtime.db.call(
        lambda db: db.execute(
            "DELETE FROM events WHERE kind='swarm.verification_recorded' AND task_id=?",
            (args["taskId"],),
        ),
        write=True,
    )
    repeated = await verify(runtime, turn, binding, args)
    assert repeated["error"] == "TASK_NOT_WAITING_VERIFICATION"
    assert "recordedVerification" not in repeated
