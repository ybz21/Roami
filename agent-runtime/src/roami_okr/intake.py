"""Validate OKR context and bind scheduled work to the project's original Main."""

import json

from roami_agent.conversation.intake import MessageAdmission
from roami_agent.protocol.errors import DomainError
from roami_okr.identity import project_conversation_identity

MAX_CONTEXT_BYTES = 65536
CONFIGURATION_KEYS = {
    "objective",
    "startDate",
    "endDate",
    "keyResults",
    "metrics",
    "swarm",
    "autoCollect",
    "initiatives",
    "dashboard",
    "team",
    "connectors",
}


def validate_context(value):
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) - {"version", "revision", "draft"}
        or type(value.get("version")) is not int
        or value["version"] != 1
        or type(value.get("revision")) is not int
        or value["revision"] < 0
        or "draft" in value
        and (not isinstance(value["draft"], dict) or set(value["draft"]) - CONFIGURATION_KEYS)
    ):
        raise DomainError("INVALID_OKR_MESSAGE_CONTEXT")
    try:
        size = len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise DomainError("INVALID_OKR_MESSAGE_CONTEXT") from exc
    if size > MAX_CONTEXT_BYTES:
        raise DomainError("OKR_MESSAGE_CONTEXT_TOO_LARGE")
    return value


def assert_context_binding(db, owner, cid):
    if project_conversation_identity(db, owner, cid)["kind"] != "project_main":
        raise DomainError("PROJECT_MAIN_IDENTITY_MISMATCH", 409)


def assert_project_main(db, owner, cid, project_id):
    identity = project_conversation_identity(db, owner, cid)
    if identity["kind"] != "project_main" or identity.get("projectId") != project_id:
        raise DomainError("PROJECT_MAIN_IDENTITY_MISMATCH", 409)


def draft_admission(owner, cid, context):
    context = validate_context(context)
    fields = {"okrContext": context}
    return MessageAdmission(fields, fields, lambda db: assert_context_binding(db, owner, cid))


async def submit(chat, owner, cid, request_key, text, attachment_ids=None, *, okr_context):
    admission = draft_admission(owner, cid, okr_context) if okr_context is not None else None
    try:
        return await chat.submit(owner, cid, request_key, text, attachment_ids, admission=admission)
    except DomainError as exc:
        if exc.code == "MESSAGE_METADATA_WITH_COMMAND":
            raise DomainError("INVALID_OKR_MESSAGE_CONTEXT") from None
        raise


def scheduled_admission(owner, cid, project_id):
    if not isinstance(project_id, str) or not project_id.strip():
        raise DomainError("INVALID_MESSAGE")
    return MessageAdmission(
        {"wakeProject": project_id},
        {"scheduled": {"projectId": project_id}},
        lambda db: assert_project_main(db, owner, cid, project_id),
    )


async def wake_project(chat, owner, cid, project_id, request_key, text):
    return await chat.submit_scheduled(
        owner, cid, request_key, text, admission=scheduled_admission(owner, cid, project_id)
    )
