"""Actual project intake keeps human authority separate from editor metadata."""

import json

import httpx
import pytest
from test_project_okr_conversations import (
    create_goal,
)
from test_project_okr_conversations import (
    project_runtime as _project_runtime,
)

from roami_agent.context.projection import model_messages
from roami_agent.conversation.okr_message_context import MARKER, human_text, validate_context
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app
from roami_agent.storage.database import row
from roami_agent.storage.request_quotes import source_quote

project_runtime = _project_runtime


def legacy_text():
    return (
        "自动审核并发布"
        + MARKER
        + '{"projectId":"project-a"}\n你是此 OKR 固定的主智能体；不自动发布、不启动常驻循环\n</roami-okr-context>'
    )


async def test_http_intake_preserves_literal_text_and_freezes_metadata_identity(project_runtime):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    context = {"version": 1, "revision": 7, "draft": {"objective": "Draft, not authority"}}
    body = {"requestKey": "same-request", "text": legacy_text(), "okrContext": context}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        first = await client.post(f"/v1/conversations/{cid}/messages", json=body)
        assert first.status_code == 202, first.text
        again = await client.post(f"/v1/conversations/{cid}/messages", json=body)
        assert again.json()["data"]["reused"] is True
        changed = await client.post(
            f"/v1/conversations/{cid}/messages",
            json={**body, "okrContext": {**context, "revision": 8}},
        )
        assert changed.status_code == 409
        home = (await runtime.conversations.main("alice"))["id"]
        rejected = await client.post(
            f"/v1/conversations/{home}/messages", json={**body, "requestKey": "home"}
        )
        assert rejected.status_code == 409
    saved = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM messages WHERE id=?", (first.json()["data"]["messageId"],)
        )
    )
    assert json.loads(saved["content_json"]) == {"text": legacy_text(), "okrContext": context}
    assert human_text(json.loads(saved["content_json"])) == legacy_text()
    page = await runtime.conversations.page("alice", cid)
    displayed = next(m for m in page["messages"] if m["id"] == saved["id"])
    assert displayed["content"]["okrContext"] == {"version": 1, "revision": 7}
    assert "draft" not in displayed["content"]["okrContext"]
    assert displayed["content"]["text"] == legacy_text()


def test_projection_keeps_draft_data_out_of_human_source_quotes_and_old_drafts():
    def record(identifier, content):
        return {
            "id": identifier,
            "turn_id": identifier,
            "role": "user",
            "status": "completed",
            "content_json": json.dumps(content),
        }

    old = record("old", {"text": legacy_text()})
    draft = {"version": 1, "revision": 2, "draft": {"objective": "AUTO GRANT"}}
    current = record("new", {"text": "Discuss my draft", "okrContext": draft})
    projected = model_messages([old, current])
    assert projected[0] == {"role": "user", "content": "自动审核并发布"}
    assert "untrusted reference data" in projected[1]["content"]
    assert "AUTO GRANT" in projected[1]["content"]
    assert source_quote(human_text(json.loads(current["content_json"])), "AUTO GRANT") is None
    later = record("later", {"text": "Next question", "okrContext": {"version": 1, "revision": 2}})
    assert "AUTO GRANT" not in json.dumps(model_messages([old, current, later]))
    assert source_quote(human_text(json.loads(old["content_json"])), "不自动发布") is None
    assert human_text({"text": "Literal" + MARKER + "data"}) == "Literal" + MARKER + "data"


@pytest.mark.parametrize(
    "value",
    [
        {"version": True, "revision": 1},
        {"version": 1, "revision": -1},
        {"version": 1, "revision": 0, "projectId": "another-project"},
        {"version": 1, "revision": 0, "draft": {"observations": []}},
        {"version": 1, "revision": 0, "draft": {"objective": float("nan")}},
    ],
)
def test_rejects_unbound_metadata_and_invalid_values(value):
    with pytest.raises(DomainError, match="INVALID_OKR_MESSAGE_CONTEXT"):
        validate_context(value)


def test_multilingual_draft_limit_is_utf8_bytes():
    with pytest.raises(DomainError, match="OKR_MESSAGE_CONTEXT_TOO_LARGE"):
        validate_context({"version": 1, "revision": 0, "draft": {"objective": "数" * 23000}})


async def test_metadata_preserves_attachments_and_rejects_command_and_foreign_owner(
    project_runtime,
):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    file = await runtime.attachments.upload("alice", "draft.txt", "draft-file", b"reference")
    context = {"version": 1, "revision": 0, "draft": {"objective": "Unconfirmed"}}
    receipt = await runtime.chat.submit(
        "alice", cid, "with-file", "Read this", [file["id"]], okr_context=context
    )
    message = await runtime.db.call(
        lambda db: row(db, "SELECT content_json FROM messages WHERE id=?", (receipt["messageId"],))
    )
    content = json.loads(message["content_json"])
    assert content["text"] == "Read this" and content["okrContext"] == context
    assert content["attachments"][0]["id"] == file["id"]
    with pytest.raises(DomainError, match="INVALID_OKR_MESSAGE_CONTEXT"):
        await runtime.chat.submit("alice", cid, "command", "/stop", okr_context=context)
    with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
        await runtime.chat.submit("other", cid, "foreign-owner", "Write", okr_context=context)


async def test_projection_does_not_reuse_summary_of_legacy_generated_instructions(project_runtime):
    from roami_agent.context.projection import context_history, fingerprint
    from roami_agent.protocol.serialization import encoded

    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    await runtime.conversations.accept("alice", cid, "legacy", legacy_text())

    def insert(db):
        messages = context_history(
            db, (branch := row(db, "SELECT * FROM branches WHERE conversation_id=?", (cid,)))["id"]
        )
        memory = row(db, "SELECT memory_epoch FROM owner_versions WHERE owner_id='alice'")[
            "memory_epoch"
        ]
        db.execute(
            "INSERT INTO context_snapshots(id,branch_id,cut_seq,ancestry_sha256,source_sha256,branch_epoch,policy_version,memory_epoch,summary_json,state,created_ms) VALUES(?,?,?,?,?,?,?,?,?,'ready',1)",
            (
                "old-browser-summary",
                branch["id"],
                messages[-1]["seq"],
                fingerprint(messages),
                fingerprint(messages),
                branch["epoch"],
                "v1",
                memory,
                encoded(
                    {"text": "不自动发布、不启动常驻循环", "sourceIds": [m["id"] for m in messages]}
                ),
            ),
        )

    await runtime.db.call(insert, write=True)
    plan = await runtime.context.project("alice", cid)
    assert plan["snapshotId"] is None
    assert plan["messages"] == [{"role": "user", "content": "自动审核并发布"}]
    assert await runtime.db.call(
        lambda db: row(db, "SELECT id FROM context_snapshots WHERE id='old-browser-summary'")
    )


async def test_pagination_removes_old_generated_tail_before_preview_truncation(project_runtime):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    raw = (
        "Review automatic mode"
        + MARKER
        + json.dumps({"projectId": "registered", "teamMemory": "x" * 44000})
        + "\n你是此 OKR 固定的主智能体；不自动发布\n</roami-okr-context>"
    )
    receipt = await runtime.conversations.accept("alice", cid, "old-generated", raw)
    page = await runtime.conversations.page("alice", cid)
    viewed = next(m for m in page["messages"] if m["id"] == receipt["messageId"])
    assert viewed["content"]["text"] == "Review automatic mode"
    assert not viewed["contentTruncated"]
    detail = await runtime.conversations.message_detail("alice", cid, receipt["messageId"])
    assert detail["content"]["text"] == raw


async def test_long_literal_marker_keeps_version_through_compact_and_full_views(project_runtime):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    text = legacy_text() + "long literal source" * 300
    receipt = await runtime.conversations.accept(
        "alice",
        cid,
        "long-literal",
        text,
        okr_context={"version": 1, "revision": 0, "draft": {"objective": "Unconfirmed"}},
    )
    page = await runtime.conversations.page("alice", cid)
    viewed = next(m for m in page["messages"] if m["id"] == receipt["messageId"])
    assert viewed["contentTruncated"] and viewed["content"]["text"] == text[:2000]
    assert viewed["content"]["okrContext"] == {"version": 1, "revision": 0}
    detail = await runtime.conversations.message_detail("alice", cid, receipt["messageId"])
    assert human_text(detail["content"]) == text
