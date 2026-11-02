"""Delivery URLs come from persisted task artifacts, not copied model identifiers."""

import json
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("html", [False, True])
async def test_main_delivery_only_normalizes_current_owned_undeleted_artifacts(store, html):
    class Report:
        model = "artifact-handoff"

        async def stream(self, messages, tools):
            text = (
                '<li><a href="/api/agent/artifacts/typo/content">report.txt</a></li>'
                if html
                else "Ready: [report.txt](/api/agent/artifacts/typo/content)."
            )
            yield ModelEvent("text", text)

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
        expected = (
            '<li><a href="">report.txt</a></li>\n\n' + f"[report.txt]({owned['downloadUrl']})"
            if html
            else f"Ready: [report.txt]({owned['downloadUrl']})."
        )
        assert text == expected
        assert all(item["id"] not in text for item in [other, unrelated, deleted])
    finally:
        await runtime.close()


def test_bare_prose_is_clickable_without_duplication_and_json_stays_structured():
    prose = "Ready: " + URL
    payload = json.dumps({"downloadUrl": URL})
    assert deliverable_links(prose, REFS) == f"Ready: [report.txt]({URL})"
    assert deliverable_links(payload, REFS) == payload
    outside = "https://example.com" + URL
    assert deliverable_links(outside, REFS).endswith(f"[report.txt]({URL})")


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "https://127.0.0.1:13579",
        "http://[::1]:3000",
        "//localhost:3000",
        "HTTP://LOCALHOST.:3000",
        "http://127.9.8.7",
    ],
)
@pytest.mark.parametrize("markdown", [False, True])
def test_loopback_download_origins_use_the_persisted_relative_reference(origin, markdown):
    url = origin + URL
    text = f"[report.txt]({url})" if markdown else "截图下载：" + url
    delivered = deliverable_links(text, REFS)
    assert delivered == (f"[report.txt]({URL})" if markdown else f"截图下载：[report.txt]({URL})")
    assert delivered.count(URL) == 1


@pytest.mark.parametrize("origin", ["https://localhost.evil.example", "https://[2001:db8::1]"])
def test_external_artifact_paths_are_preserved_without_hiding_owned_delivery(origin):
    outside = origin + URL
    delivered = deliverable_links(outside, REFS)
    assert delivered == outside + f"\n\n[report.txt]({URL})"


def test_unknown_loopback_and_bare_artifact_ids_cannot_be_delivered():
    for url in [
        "http://localhost:3000/api/agent/artifacts/foreign/content",
        "/api/agent/artifacts/foreign/content",
    ]:
        delivered = deliverable_links("下载：" + url, REFS)
        assert "foreign" not in delivered and "localhost" not in delivered
        assert URL in delivered
    encoded = "http://localhost:3000/api/file/raw?path=%2Fapi%2Fagent%2Fartifacts%2Fowned%2Fcontent"
    assert deliverable_links(f"[report.txt]({encoded})", REFS) == f"[report.txt]({URL})"


@pytest.mark.parametrize("markdown", [False, True])
@pytest.mark.parametrize("origin", ["", "http://localhost:3000"])
async def test_main_delivery_has_one_clickable_readable_owned_url(store, markdown, origin):
    reference = None

    class Report:
        model = "loopback-capture-handoff"

        async def stream(self, messages, tools):
            url = origin + reference["downloadUrl"]
            yield ModelEvent("text", f"[截图]({url})" if markdown else "截图下载：" + url)

    runtime = Runtime(store, Report())
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], "截一张网页给我", key="capture", record_intent=True
        )
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        reference = await runtime.artifacts.put(
            "alice", b"image-bytes", name="capture.png", mime_type="image/png", task_id=task["id"]
        )
        await runtime.dispatch.complete(
            task,
            run,
            {"state": "succeeded", "summary": "截图完成", "artifactRefs": [reference]},
            "succeeded",
        )
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
        messages = (await runtime.conversations.messages("alice", c["id"]))["messages"]
        text = messages[-1]["content"]["text"]
        assert "localhost" not in text
        assert text.count(reference["downloadUrl"]) == 1
        assert f"]({reference['downloadUrl']})" in text
        assert (await runtime.artifacts.read("alice", reference["id"]))[1] == b"image-bytes"
    finally:
        await runtime.close()


def test_loopback_download_in_json_remains_a_relative_string():
    payload = json.dumps({"downloadUrl": "http://localhost:3000" + URL})
    delivered = deliverable_links(payload, REFS)
    assert json.loads(delivered) == {"downloadUrl": URL}


@pytest.mark.parametrize("punctuation", [".", "。", "！"])
def test_bare_loopback_download_remains_clickable_before_sentence_punctuation(punctuation):
    text = "下载：http://localhost:3000" + URL + punctuation
    assert deliverable_links(text, REFS) == f"下载：[report.txt]({URL})" + punctuation


@pytest.mark.parametrize("quote", ['"', "'", ""])
@pytest.mark.parametrize("origin", ["", "http://localhost:3000"])
def test_html_attribute_keeps_a_url_and_gets_a_separate_clickable_download(quote, origin):
    text = f"<li><a href={quote}{origin}{URL}{quote}>report.txt</a></li>"
    expected = f"<li><a href={quote}{URL}{quote}>report.txt</a></li>\n\n[report.txt]({URL})"
    assert deliverable_links(text, REFS) == expected


def test_quoted_angle_bracket_does_not_end_the_attribute_context():
    text = f'<a title="download > preview" href="{URL}">report.txt</a>'
    assert deliverable_links(text, REFS) == text + f"\n\n[report.txt]({URL})"


def test_html_attribute_does_not_hide_a_missing_other_artifact():
    refs = [*REFS, {"id": "deck", "name": "slides.pptx"}]
    text = f'<a href="{URL}">report.txt</a>'
    delivered = deliverable_links(text, refs)
    assert (
        delivered
        == text + f"\n\n[report.txt]({URL})\n[slides.pptx](/api/agent/artifacts/deck/content)"
    )


def test_unowned_html_attribute_stays_unlinked_and_cannot_suppress_owned_delivery():
    text = '<a href="/api/agent/artifacts/foreign/content">report.txt</a>'
    delivered = deliverable_links(text, REFS)
    assert delivered == '<a href="">report.txt</a>\n\n' + f"[report.txt]({URL})"


def test_actual_html_list_recipe_keeps_one_renderable_canonical_link_on_repeat():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/html-artifact-delivery.json").read_text()
    )
    result = deliverable_links(fixture["text"], fixture["references"])
    assert result == fixture["expected"]
    assert deliverable_links(result, fixture["references"]) == result


def test_existing_markdown_nested_in_html_attribute_is_repaired():
    text = f'<a href="[report.txt]({URL})">report.txt</a>'
    assert deliverable_links(text, REFS) == (
        f'<a href="{URL}">report.txt</a>\n\n[report.txt]({URL})'
    )
