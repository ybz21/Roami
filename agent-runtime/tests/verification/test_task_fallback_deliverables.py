"""A blocked completion report must keep persisted output available without inventing success."""

import json
from pathlib import Path

import pytest
from test_local_go_gateway import gateway_fixture
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import ModelAdmissionRejected
from roami_agent.providers.factory import configured_provider
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row

CONTROLS = json.loads(
    (Path(__file__).parents[3] / "cases/case-103-mech-tf02/input/controls.json").read_text()
)


async def completed_task(store, tmp_path, state):
    socket = str(tmp_path / "gateway.sock")
    settings = Settings(
        endpoint="https://must-not-connect.invalid/v1", model="fixture", model_gateway_socket=socket
    )
    provider = configured_provider(settings, "main")
    runtime = Runtime(store, provider, settings=settings, memory_model=ConversationModel())
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice", conversation["id"], "Save report", key="report", record_intent=True
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    owned = await runtime.artifacts.put(
        "alice", b"saved report", name="report.txt", mime_type="text/plain", task_id=task["id"]
    )
    foreign = await runtime.artifacts.put(
        "bob", b"private", name="private.txt", mime_type="text/plain"
    )
    unrelated = await runtime.artifacts.put(
        "alice", b"unrelated", name="unrelated.txt", mime_type="text/plain"
    )
    deleted = await runtime.artifacts.put(
        "alice", b"deleted", name="deleted.txt", mime_type="text/plain", task_id=task["id"]
    )
    await runtime.artifacts.delete("alice", deleted["id"])
    await runtime.dispatch.complete(
        task,
        run,
        {
            "state": "succeeded",
            "summary": "Executor claims success: https://untrusted.invalid/report",
            "artifactRefs": [{**owned, "name": "forged.txt"}, foreign, unrelated, deleted],
        },
        state,
    )
    job = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
            (task["id"],),
        )
    )
    turn = await runtime.mailbox.claim(job)
    return (
        runtime,
        provider,
        conversation,
        task,
        turn,
        json.loads(job["payload_json"])["completion"],
        socket,
        owned,
    )


@pytest.mark.parametrize("state", CONTROLS["task_states"])
async def test_blocked_summary_preserves_owned_download_and_actual_task_state(
    store, tmp_path, state
):
    runtime, provider, conversation, _, turn, completion, socket, owned = await completed_task(
        store, tmp_path, state
    )
    seen = []
    try:
        async with gateway_fixture(socket, seen, status=409, code=CONTROLS["report_error"]):
            with pytest.raises(ModelAdmissionRejected):
                await runtime.loop.run(turn, "main", completion=completion)
        view = await runtime.conversations.messages("alice", conversation["id"])
        fallback = [m for m in view["messages"] if m["content"].get("taskStatus")]
        assert len(fallback) == 1
        content = fallback[0]["content"]
        assert content.get("text") == f"[report.txt]({owned['downloadUrl']})"
        assert content["taskStatus"]["state"] == state
        assert content["taskStatus"]["reportError"] == CONTROLS["report_error"]
        assert content["taskStatus"]["errorCode"] is None
        assert (await runtime.artifacts.read("alice", owned["id"]))[1] == b"saved report"
        assert len(seen) == 1
        await runtime.journal.fail(turn, "failed", CONTROLS["report_error"], completion=completion)
        view = await runtime.conversations.messages("alice", conversation["id"])
        assert sum(bool(m["content"].get("taskStatus")) for m in view["messages"]) == 1
    finally:
        await runtime.close()
        await provider.close()


@pytest.mark.parametrize("guard", [guard for guard in CONTROLS["guards"] if guard != "duplicate"])
async def test_stale_or_withdrawn_completion_never_restores_output(store, tmp_path, guard):
    runtime, provider, conversation, task, turn, completion, _, _ = await completed_task(
        store, tmp_path, "succeeded"
    )
    try:
        if guard == "revision":
            completion["taskRevision"] += 1
        elif guard == "state":
            completion["state"] = "failed"
        elif guard == "owner":
            turn = {**turn, "owner_id": "bob"}
        elif guard == "branch":
            turn = {**turn, "branch_id": "other-branch"}
        elif guard == "forgotten":
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES(?,?,?,?)",
                    ("alice", task["origin_message_id"], "user_forgotten", 1),
                ),
                write=True,
            )
        await runtime.journal.fail(
            turn,
            "interrupted" if guard == "interrupted" else "failed",
            CONTROLS["report_error"],
            completion=completion,
        )
        view = await runtime.conversations.messages("alice", conversation["id"])
        assert not any(m["content"].get("taskStatus") for m in view["messages"])
    finally:
        await runtime.close()
        await provider.close()


async def test_withheld_retrieval_candidate_is_not_restored_as_a_deliverable(store, tmp_path):
    runtime, provider, conversation, _, turn, completion, _, owned = await completed_task(
        store, tmp_path, "failed"
    )
    try:
        completion["result"]["errorCode"] = CONTROLS["withheld_error"]
        await runtime.journal.fail(turn, "failed", CONTROLS["report_error"], completion=completion)
        view = await runtime.conversations.messages("alice", conversation["id"])
        fallback = next(m["content"] for m in view["messages"] if m["content"].get("taskStatus"))
        assert "text" not in fallback
        assert owned["id"] not in json.dumps(fallback)
        assert fallback["taskStatus"]["state"] == "failed"
    finally:
        await runtime.close()
        await provider.close()
