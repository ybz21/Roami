"""Independent session results survive Main's own review and later task revisions."""

import json

import httpx
import pytest
import test_swarm_main_verification as verification_cases

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.http import create_app
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row

review_case = verification_cases.review_case


@pytest.mark.parametrize("fault", [None, "stop", "forget", "delete", "stop_and_forget"])
async def test_report_after_review_and_new_revision_keeps_source_privacy(review_case, store, fault):
    runtime, original, binding, args, artifact = review_case
    await runtime.loop.run(original, "main")
    job = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='turn.run' "
            "AND json_extract(payload_json,'$.completion.taskId')=? "
            "AND json_extract(payload_json,'$.completion.state')='waiting_user'",
            (args["taskId"],),
        )
    )
    turn = await runtime.mailbox.claim(job)
    dispatches = []

    async def resolve(kind, identifier):
        return {"sessionId": identifier}

    class MainReview:
        model = "review-before-independent-return"

        def __init__(self):
            self.step = 0

        async def stream(self, messages, tools):
            step, self.step = self.step, self.step + 1
            if step == 0:
                call = verification_cases.wire("read", {"path": "artifact://" + artifact["id"]})
            elif step == 1:
                call = verification_cases.wire(
                    "bash", {"command": "roami swarm verify --input '" + json.dumps(args) + "'"}
                )
            else:
                dispatches.append(
                    await runtime.session_dispatches.prepare(
                        "unrelated-legacy-session",
                        "Complete the independently requested work",
                        "independent-return",
                        {**binding, "turnId": turn["id"]},
                        resolve=resolve,
                    )
                )
                await runtime.session_dispatches.record_delivery(
                    dispatches[-1], {"sessionId": "unrelated-legacy-session", "state": "delivered"}
                )
                yield ModelEvent("text", "Review finished; independent session may return later.")
                return
            yield ModelEvent("tool", call)

    runtime.loop.model = MainReview()
    await runtime.loop.run(turn, "main", completion=json.loads(job["payload_json"])["completion"])
    assert len(dispatches) == 1
    dispatch = dispatches[0]
    await runtime.tasks.revisions.request(
        "alice", args["taskId"], "Next bounded round", 1, "next-round"
    )
    await runtime.tasks.revisions.advance()
    with pytest.raises(DomainError, match="TASK_RESULT_SUPERSEDED"):
        await store.call(
            lambda db: assert_context_admitted(db, {"id": turn["id"], "owner_id": "alice"})
        )

    def change_sources(db):
        if fault in {"stop", "stop_and_forget"}:
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                "VALUES(?,'control.stop',?,?,?,'done',?)",
                (
                    identity(),
                    binding["conversation"],
                    "stop-old",
                    json.dumps({"turnId": turn["id"]}),
                    now_ms(),
                ),
            )
        if fault in {"forget", "stop_and_forget"}:
            db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) "
                "VALUES('alice',?,'forgotten',?)",
                (binding["originMessageId"], now_ms()),
            )
        if fault == "delete":
            db.execute(
                "UPDATE messages SET deleted_ms=?,status='deleted' WHERE id=?",
                (now_ms(), binding["originMessageId"]),
            )

    await store.call(change_sources, write=True)
    result = {"key": "final", "status": "completed", "summary": "Independent result, not reviewed"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        response = await client.post(
            f"/internal/session-dispatches/{dispatch['id']}/reply", json=result
        )
        if fault in {"forget", "delete", "stop_and_forget"}:
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == "CONTEXT_SOURCE_FORGOTTEN"
            assert not await store.call(
                lambda db: row(
                    db,
                    "SELECT 1 FROM session_dispatch_reports WHERE dispatch_id=?",
                    (dispatch["id"],),
                )
            )
            return
        assert response.status_code == 200, response.text
        receipt = response.json()["data"]
        assert receipt["verified"] is False
        again = await client.post(
            f"/internal/session-dispatches/{dispatch['id']}/reply", json=result
        )
        assert again.json()["data"]["messageId"] == receipt["messageId"]
        assert again.json()["data"]["reused"] is True
    returned = await store.call(
        lambda db: row(db, "SELECT branch_id FROM messages WHERE id=?", (receipt["messageId"],))
    )
    assert returned["branch_id"] == dispatch["branch_id"]
    task = await store.call(
        lambda db: row(db, "SELECT state,revision FROM tasks WHERE id=?", (args["taskId"],))
    )
    assert task["revision"] == 2 and task["state"] != "succeeded"
