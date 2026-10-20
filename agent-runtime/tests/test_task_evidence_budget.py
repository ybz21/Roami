"""Large executor reports cannot consume the Main conversation input budget."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.context.task_evidence import completion_evidence
from roami_agent.context.token_estimate import request_tokens, text_tokens
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row


@pytest.mark.parametrize("text", ["plain", "中文", "\x00\n\t", '"\\'])
@pytest.mark.parametrize("budget", [1024, 6000])
def test_completion_excerpt_is_bounded_and_preserves_authority_and_unknown_flags(text, budget):
    completion = {
        "taskId": "task-1",
        "runId": "run-1",
        "taskRevision": 2,
        "state": "interrupted",
        "result": {
            "state": "succeeded",
            "summary": text * 20000,
            "outcomeKnown": False,
            "inputStopped": False,
            "checks": [{"log": text * 5000}] * 20,
            "artifactRefs": [{"id": "artifact-1", "name": text * 5000}],
        },
    }
    original = encoded(completion)
    excerpt = completion_evidence(completion, budget=budget)
    assert text_tokens(encoded(excerpt)) <= budget
    assert excerpt["state"] == "interrupted"
    assert excerpt["result"]["state"] == "succeeded"
    assert excerpt["result"]["outcomeKnown"] is False
    assert excerpt["result"]["inputStopped"] is False
    assert excerpt["result"]["checksCount"] == 20
    assert excerpt["result"]["artifactIds"] == ["artifact-1"]
    assert excerpt["evidenceTruncated"] is True
    assert excerpt["resultRef"] == {"taskId": "task-1", "runId": "run-1", "taskRevision": 2}
    assert encoded(completion) == original


def test_small_completion_preserves_existing_evidence():
    completion = {"taskId": "one", "state": "succeeded", "result": {"summary": "Verified"}}
    assert completion_evidence(completion, budget=6000) == completion


async def test_long_report_generates_main_reply_while_full_attempt_evidence_is_retained(store):
    class CapturedMain(ConversationModel):
        def __init__(self):
            self.prompts = []

        async def stream(self, messages, tools):
            self.prompts.append(messages)
            yield ModelEvent("text", "The result is ready for review.")

    async def verifier(task, result):
        return True

    model = CapturedMain()
    runtime = Runtime(store, model, verifier=verifier)
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "Research", key="large", record_intent=True
        )
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        report = {"state": "succeeded", "summary": "原始结果" * 15000}
        await runtime.tasks.report("alice", task["id"], run["id"], 1, report)
        job = await store.call(
            lambda db: row(
                db, "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (task["id"],)
            )
        )
        await runtime.dispatch.verify(job)
        completion_job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
                (task["id"],),
            )
        )
        turn = await runtime.mailbox.claim(completion_job)
        await runtime.loop.run(
            turn, "main", completion=json.loads(completion_job["payload_json"])["completion"]
        )
        assert len(model.prompts) == 1
        assert request_tokens(model.prompts[0], []) < 6000
        source = next(
            item
            for item in model.prompts[0]
            if item["content"].startswith("Background task result")
        )
        assert '"evidenceTruncated":true' in source["content"]
        retained = await store.call(
            lambda db: row(db, "SELECT result_json FROM task_attempts WHERE id=?", (run["id"],))
        )
        assert json.loads(retained["result_json"]) == report
        view = await runtime.conversations.messages("alice", conversation["id"])
        assert view["messages"][-1]["content"]["text"] == "The result is ready for review."
    finally:
        await runtime.close()


@pytest.mark.parametrize("budget", [1024, 6000])
async def test_large_report_keeps_download_links_in_main_context(store, budget):
    runtime = Runtime(store, ConversationModel())
    try:
        artifact = await runtime.artifacts.put(
            "alice", b"Verified report", mime_type="text/plain", name="report.txt"
        )
        completion = {
            "taskId": "report-task",
            "state": "waiting_user",
            "result": {
                "state": "succeeded",
                "summary": "Detailed execution log. " * 20000,
                "artifactRefs": [artifact],
            },
        }
        excerpt = completion_evidence(completion, budget=budget)
        assert text_tokens(encoded(excerpt)) <= budget
        assert excerpt["state"] == "waiting_user"
        assert excerpt["result"]["artifactRefs"] == [
            {"id": artifact["id"], "name": "report.txt", "downloadUrl": artifact["downloadUrl"]}
        ]
        assert excerpt["resultRef"]["taskId"] == "report-task"
        assert completion["result"]["summary"].endswith("Detailed execution log. ")
    finally:
        await runtime.close()


def test_large_reference_metadata_cannot_expand_completion_budget():
    completion = {
        "taskId": "task-1",
        "state": "interrupted",
        "result": {
            "outcomeKnown": False,
            "summary": "x" * 20000,
            "artifactRefs": [
                {"id": str(index), "name": "report" * 2000, "downloadUrl": "/" + "中" * 2000}
                for index in range(4)
            ],
        },
    }
    excerpt = completion_evidence(completion, budget=1024)
    assert text_tokens(encoded(excerpt)) <= 1024
    assert excerpt["result"]["outcomeKnown"] is False
    assert excerpt["result"]["artifactRefsCount"] == 4
    assert excerpt["resultRef"]["taskId"] == "task-1"
