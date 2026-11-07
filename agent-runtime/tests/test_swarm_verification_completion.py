"""An actual task-result Main turn can finish its own independent Swarm review."""

import json

import pytest
import test_swarm_main_verification as verification_cases

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_completion import self_verified_completion

review_case = verification_cases.review_case


@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "ui",
        "forget",
        "stop",
        "steer",
        "revision",
        "foreign_turn",
        "foreign_main",
        "wrong_run",
        "latest_run",
    ],
)
async def test_task_result_main_reads_verifies_posts_and_finishes_without_rewriting_manifests(
    review_case, store, accepted, fault
):
    runtime, original, binding, args, artifact = review_case
    await runtime.loop.run(original, "main")
    job = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=? AND json_extract(payload_json,'$.completion.state')='waiting_user'",
            (args["taskId"],),
        )
    )
    turn = await runtime.mailbox.claim(job)
    assert turn and turn["trigger_kind"] == "completion"
    completion = json.loads(job["payload_json"])["completion"]
    html = await runtime.artifacts.put(
        "alice",
        b"<!doctype html><p>Actual report</p>",
        mime_type="text/html",
        name="report.html",
        task_id=args["taskId"],
        metadata={"runId": args["runId"]},
    )
    payload = {**args, "accepted": accepted, "artifactIds": [artifact["id"], html["id"]]}

    class MainReview:
        model = "scripted-main-review"

        def __init__(self):
            self.step = 0
            self.before = {}
            self.prompts = []

        async def stream(self, messages, tools):
            self.prompts.append(messages)
            step, self.step = self.step, self.step + 1
            if step < 2:
                ident = [artifact["id"], html["id"]][step]
                call = verification_cases.wire("read", {"path": "artifact://" + ident})
            elif step == 2:
                if fault == "ui":
                    await runtime.dispatch.confirm(
                        "alice",
                        args["taskId"],
                        accepted,
                        revision=args["revision"],
                        run_id=args["runId"],
                    )
                self.before = await store.call(
                    lambda db: {
                        p["id"]: p["evidence"]
                        for p in rows(
                            db,
                            "SELECT id,json_extract(parts_json,'$.taskEvidence') AS evidence FROM prompt_manifests WHERE turn_id=?",
                            (turn["id"],),
                        )
                    }
                )
                call = verification_cases.wire(
                    "bash", {"command": "roami swarm verify --input '" + json.dumps(payload) + "'"}
                )
            elif step == 3:
                if fault is None:
                    partial = {"id": turn["id"], "owner_id": "alice"}
                    await store.call(lambda db: assert_context_admitted(db, partial))
                    for wrong in ({"owner_id": "bob"}, {"conversation_id": "another-main"}):
                        assert not await store.call(
                            lambda db, wrong=wrong: self_verified_completion(
                                db, {**partial, **wrong}, completion
                            )
                        )
                    mid = await store.call(
                        lambda db: row(
                            db,
                            "SELECT id FROM messages WHERE turn_id=? AND role='assistant' "
                            "ORDER BY seq DESC LIMIT 1",
                            (turn["id"],),
                        )["id"]
                    )
                    await runtime.journal.preview(turn, mid, "Review completed; drafting reply")
                    page = await runtime.conversations.page("alice", turn["conversation_id"])
                    assert any(
                        m["content"].get("replyPreview", {}).get("text")
                        == "Review completed; drafting reply"
                        for m in page["messages"]
                    )
                current = next(
                    m["content"]
                    for m in messages
                    if isinstance(m.get("content"), str)
                    and m["content"].startswith("Background task result")
                )
                assert (
                    "contextExcluded" not in current
                    and "source information was forgotten" not in current
                )
                assert '"state":"' + ("succeeded" if accepted else "failed") + '"' in current
                if fault == "forget":
                    await store.call(
                        lambda db: db.execute(
                            "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',?)",
                            (binding["originMessageId"], now_ms()),
                        ),
                        write=True,
                    )
                elif fault == "stop":
                    await store.call(
                        lambda db: db.execute(
                            "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'control.stop',?,?,?,'done',?)",
                            (
                                identity(),
                                binding["conversation"],
                                "stop-current",
                                json.dumps({"turnId": turn["id"]}),
                                now_ms(),
                            ),
                        ),
                        write=True,
                    )
                elif fault in {"steer", "revision"}:
                    await runtime.tasks.revisions.request(
                        "alice", args["taskId"], "New requirements", 1, "steer-after-review"
                    )
                    if fault == "revision":
                        await runtime.tasks.revisions.advance()
                elif fault in {"foreign_turn", "foreign_main", "wrong_run"}:
                    field = {
                        "foreign_turn": "mainTurnId",
                        "foreign_main": "mainConversationId",
                        "wrong_run": "runId",
                    }[fault]
                    await store.call(
                        lambda db: db.execute(
                            "UPDATE events SET payload_json=json_set(payload_json,?,?) WHERE kind='swarm.verification_recorded' AND turn_id=?",
                            ("$." + field, identity(), turn["id"]),
                        ),
                        write=True,
                    )
                elif fault == "latest_run":

                    def newer(db):
                        previous = row(
                            db, "SELECT * FROM task_attempts WHERE id=?", (args["runId"],)
                        )
                        previous.update(
                            id=identity(),
                            launch_id=identity(),
                            attempt_no=previous["attempt_no"] + 1,
                        )
                        db.execute(
                            "INSERT INTO task_attempts("
                            + ",".join(previous)
                            + ") VALUES("
                            + ",".join("?" for _ in previous)
                            + ")",
                            tuple(previous.values()),
                        )

                    await store.call(newer, write=True)
                call = verification_cases.wire(
                    "bash",
                    {
                        "command": "roami swarm post --input '"
                        + json.dumps(
                            {"swarmId": args["swarmId"], "text": "Independent Main review finished"}
                        )
                        + "'"
                    },
                )
            else:
                yield ModelEvent("text", "Independent review completed.")
                return
            yield ModelEvent("tool", call)

    model = MainReview()
    runtime.loop.model = model
    if fault:
        expected = (
            "CONTEXT_SOURCE_FORGOTTEN"
            if fault == "forget"
            else "TURN_INTERRUPTED"
            if fault == "stop"
            else "TASK_RESULT_SUPERSEDED"
        )
        with pytest.raises(DomainError, match=expected):
            await runtime.loop.run(turn, "main", completion=completion)
        assert not await store.call(
            lambda db: row(
                db,
                "SELECT id FROM swarm_posts WHERE swarm_id=? AND text='Independent Main review finished'",
                (args["swarmId"],),
            )
        )
        return
    await runtime.loop.run(turn, "main", completion=completion)
    result = await store.call(
        lambda db: row(db, "SELECT state FROM turns WHERE id=?", (turn["id"],))
    )
    assert result["state"] == "completed" and model.step == 5
    manifest = await store.call(
        lambda db: rows(
            db,
            "SELECT id,json_extract(parts_json,'$.taskEvidence') AS evidence FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no",
            (turn["id"],),
        )
    )
    assert all(p["evidence"] == model.before[p["id"]] for p in manifest if p["id"] in model.before)
    assert json.loads(manifest[0]["evidence"])["state"] == "waiting_user"
    assert json.loads(manifest[-1]["evidence"])["state"] == ("succeeded" if accepted else "failed")
    audit = await store.call(
        lambda db: row(
            db,
            "SELECT id FROM events WHERE kind='swarm.verification_recorded' AND turn_id=?",
            (turn["id"],),
        )
    )
    assert audit
    assert not await store.call(
        lambda db: row(
            db, "SELECT id FROM events WHERE kind='turn.failed' AND turn_id=?", (turn["id"],)
        )
    )
