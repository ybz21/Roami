"""Delivery URLs come from persisted task artifacts, not copied model identifiers."""

import json

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.replies.artifact_links import deliverable_links
from roami_agent.storage.database import row

REFS = [{"id": "owned", "name": "report.txt"}]
URL = "/api/agent/artifacts/owned/content"


def test_copied_id_and_encoded_api_path_are_corrected_without_changing_other_links():
    text = (
        "Report: [report.txt](/api/agent/artifacts/typo/content). PR: [PR](https://example.com/pr)."
    )
    assert deliverable_links(text, REFS) == text.replace("/typo/", "/owned/")
    assert (
        deliverable_links(
            "[report.txt](/api/file/raw?path=%2Fapi%2Fagent%2Fartifacts%2Fowned%2Fcontent)", REFS
        )
        == f"[report.txt]({URL})"
    )


def test_missing_links_are_added_and_duplicate_names_are_never_guessed():
    assert deliverable_links("Ready.", REFS) == f"Ready.\n\n[report.txt]({URL})"
    refs = [*REFS, {"id": "second", "name": "report.txt"}]
    corrected = deliverable_links("[report.txt](/api/agent/artifacts/typo/content)", refs)
    assert corrected.startswith("report.txt\n\n")
    assert "typo" not in corrected and "/owned/" in corrected and "/second/" in corrected
    assert deliverable_links("No saved files.", []) == "No saved files."


async def test_main_delivery_only_normalizes_current_owned_undeleted_artifacts(store):
    class Report:
        model = "artifact-handoff"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "Ready: [report.txt](/api/agent/artifacts/typo/content).")

    runtime = Runtime(store, Report())
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "Create report", key="report", record_intent=True
        )
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        owned = await runtime.artifacts.put(
            "alice", b"report", name="report.txt", mime_type="text/plain", task_id=task["id"]
        )
        other = await runtime.artifacts.put(
            "bob", b"private", name="private.txt", mime_type="text/plain"
        )
        unrelated = await runtime.artifacts.put(
            "alice", b"unrelated", name="unrelated.txt", mime_type="text/plain"
        )
        deleted = await runtime.artifacts.put(
            "alice", b"deleted", name="deleted.txt", mime_type="text/plain", task_id=task["id"]
        )
        await runtime.artifacts.delete("alice", deleted["id"])
        result = {
            "state": "succeeded",
            "summary": "Verified report.",
            "artifactRefs": [owned, other, unrelated, deleted],
        }
        await runtime.dispatch.complete(task, run, result, "succeeded")
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
                (task["id"],),
            )
        )
        turn = await runtime.mailbox.claim(job)
        await runtime.loop.run(
            turn, "main", completion=json.loads(job["payload_json"])["completion"]
        )
        messages = (await runtime.conversations.messages("alice", conversation["id"]))["messages"]
        text = messages[-1]["content"]["text"]
        assert text == f"Ready: [report.txt]({owned['downloadUrl']})."
        assert all(item["id"] not in text for item in [other, unrelated, deleted])
    finally:
        await runtime.close()
