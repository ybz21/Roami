import io
import json
from dataclasses import replace

import httpx
import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from roami_agent.app import Runtime
from roami_agent.context.chat_images import ChatImages
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


class Model:
    model = "attachment-fixture"

    async def stream(self, messages, tools):
        yield ModelEvent("text", "fixture")


def document():
    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (PDF fixture token 4826) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


async def test_upload_send_replay_scope_and_context_delete(store):
    runtime = Runtime(store, Model())
    try:
        conversation = await runtime.conversations.create("local")
        other = await runtime.conversations.create("other")
        file = await runtime.attachments.upload(
            "local", "计划.md", "upload-plan", "三项工作：收件、派活、回报。".encode()
        )
        assert (
            await runtime.attachments.upload(
                "local", "计划.md", "upload-plan", "三项工作：收件、派活、回报。".encode()
            )
        )["id"] == file["id"]
        with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
            await runtime.attachments.upload("local", "计划.md", "upload-plan", b"changed")
        with pytest.raises(DomainError, match="ATTACHMENT_NOT_FOUND"):
            await runtime.chat.submit("other", other["id"], "foreign", "inspect", [file["id"]])
        receipt = await runtime.chat.submit(
            "local", conversation["id"], "send-plan", "", [file["id"]]
        )
        replay = await runtime.chat.submit(
            "local", conversation["id"], "send-plan", "", [file["id"]]
        )
        assert replay["reused"] and replay["messageId"] == receipt["messageId"]
        view = await runtime.conversations.messages("local", conversation["id"])
        assert view["messages"][0]["content"]["attachments"][0]["name"] == "计划.md"
        plan = await runtime.context.project("local", conversation["id"])
        assert "三项工作" in json.dumps(plan, ensure_ascii=False)
        assert plan["attachmentEvidence"][0]["artifactId"] == file["id"]
        with pytest.raises(DomainError, match="ATTACHMENT_ALREADY_SENT"):
            await runtime.attachments.remove_draft("local", file["id"])
        with pytest.raises(DomainError, match="ATTACHMENT_ALREADY_SENT"):
            await runtime.chat.submit(
                "local", conversation["id"], "duplicate-use", "again", [file["id"]]
            )
        await runtime.artifacts.delete("local", file["id"])
        plan = await runtime.context.project("local", conversation["id"])
        assert "三项工作" not in json.dumps(plan, ensure_ascii=False)
        assert not plan["attachmentEvidence"]
    finally:
        await runtime.close()


async def test_pdf_preview_is_real_bounded_and_binary_is_explicit(store):
    runtime = Runtime(store, Model())
    try:
        pdf = await runtime.attachments.upload("local", "brief.pdf", "pdf", document())
        assert "4826" in pdf["metadata"]["preview"]["text"]
        bad = await runtime.attachments.upload("local", "bad.pdf", "bad-pdf", b"%PDF-invalid")
        assert bad["metadata"]["preview"]["state"] == "unavailable"
        binary = await runtime.attachments.upload("local", "archive.bin", "binary", b"\x00\xff\xfe")
        assert binary["metadata"]["preview"]["state"] == "unsupported"
        text = await runtime.attachments.upload("local", "large.txt", "text", b"a" * 10000)
        assert text["metadata"]["preview"]["truncated"]
        assert len(text["metadata"]["preview"]["text"]) == 2000
        await runtime.attachments.remove_draft("local", text["id"])
        with pytest.raises(DomainError, match="ATTACHMENT_NOT_FOUND"):
            await runtime.attachments.upload("local", "large.txt", "text", b"a" * 10000)
    finally:
        await runtime.close()


async def test_image_capability_wire_and_reference_only_history(store):
    settings = Settings(
        endpoint="http://127.0.0.1:1/v1", model="fixture", model_capabilities={"images": True}
    )
    runtime = Runtime(store, Model(), settings=settings)
    try:
        body = io.BytesIO()
        Image.new("RGB", (32, 24), "white").save(body, "PNG")
        image = await runtime.attachments.upload("local", "figure.png", "image", body.getvalue())
        conversation = await runtime.conversations.create("local")
        await runtime.chat.submit(
            "local", conversation["id"], "image-turn", "read image", [image["id"]]
        )
        plan = await runtime.context.project("local", conversation["id"])
        _, prompt = await ChatImages(store, runtime.artifacts, settings).attach(
            {"owner_id": "local"}, plan, plan["messages"]
        )
        assert "data:image/png;base64," in json.dumps(prompt)
        raw = await store.call(
            lambda db: row(db, "SELECT content_json FROM messages WHERE role='user'")
        )
        assert "base64" not in raw["content_json"]
        no_images = replace(settings, model_capabilities={})
        _, prompt = await ChatImages(store, runtime.artifacts, no_images).attach(
            {"owner_id": "local"}, plan, plan["messages"]
        )
        assert "data:image" not in json.dumps(prompt)
        assert "not configured for image input" in prompt[-1]["content"]
    finally:
        await runtime.close()


async def test_real_http_upload_limits_commands_and_draft_delete(store):
    runtime = Runtime(store, Model())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://fixture",
            headers={"X-Roami-Owner": "local"},
        ) as client:
            response = await client.post(
                "/v1/attachments",
                params={"filename": "note.txt", "requestKey": "upload-http"},
                content=b"http-evidence",
            )
            assert response.status_code == 201
            aid = response.json()["data"]["id"]
            cid = (await runtime.conversations.create("local"))["id"]
            response = await client.post(
                f"/v1/conversations/{cid}/messages",
                json={"requestKey": "slash-file", "text": "/compact", "attachmentIds": [aid]},
            )
            assert (
                response.status_code == 400
                and response.json()["error"]["code"] == "ATTACHMENTS_WITH_COMMAND"
            )
            assert (await client.delete("/v1/attachments/" + aid)).status_code == 200
            assert (
                await client.post(
                    "/v1/attachments",
                    params={"filename": "../note.txt", "requestKey": "bad-name"},
                    content=b"bad",
                )
            ).status_code == 400
            assert (
                await client.post(
                    "/v1/attachments",
                    params={"filename": "huge", "requestKey": "huge"},
                    content=b"x" * (10 * 1024 * 1024 + 1),
                )
            ).status_code == 413
    finally:
        await runtime.close()
