"""Typed project reviews with source-bound operation identity and small saved receipts."""

from jsonschema import Draft202012Validator, ValidationError

from roami_agent.conversation.project_okr import bound_project, operation
from roami_agent.protocol.errors import DomainError, ProjectReviewInputError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.swarm_coordination_writes import project_receipt


def review_fields():
    return {
        "revision": {"type": "integer", "minimum": 0, "maximum": 9223372036854775807},
        "summary": {
            "type": "string",
            "minLength": 1,
            "pattern": r"\S",
            "description": "Real findings grounded in the current project evidence; never placeholder or schema-probing content.",
        },
        "actions": {
            "type": "string",
            "description": "The actual next action, or empty when none is needed.",
        },
    }


def review_schema():
    return object_schema(
        {
            **review_fields(),
            "operationKey": {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r"\S"},
        },
        ["revision", "summary"],
    )


def checked_review(payload):
    try:
        Draft202012Validator(review_schema()).validate(payload)
        if type(payload["revision"]) is not int:
            raise ProjectReviewInputError
        payload["summary"].encode("utf-8")
        payload.get("actions", "").encode("utf-8")
        payload.get("operationKey", "").encode("utf-8")
    except (ValidationError, UnicodeError):
        raise ProjectReviewInputError from None
    return dict(payload)


def review_payload(args, binding):
    payload = checked_review(args)
    expected = binding.get("coordinationProjectWrite")
    if expected is not None:
        if expected.get("kind") != "review":
            raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
        key = expected["key"]
    else:
        turn = binding.get("turnId")
        if not isinstance(turn, str) or not turn or len(turn) > 100:
            raise DomainError("PROJECT_REVIEW_TURN_REQUIRED", 403)
        key = "review:" + turn
    return {**payload, "actions": payload.get("actions", ""), "operationKey": key}


def review_receipt(workspace, project_id, payload):
    if not isinstance(workspace, dict) or workspace.get("projectId") != project_id:
        raise DomainError("PROJECT_REVIEW_RECEIPT_UNAVAILABLE", 503)
    if not isinstance(workspace.get("projectFiles"), dict) or not isinstance(
        workspace.get("reviews"), list
    ):
        raise DomainError("PROJECT_REVIEW_RECEIPT_UNAVAILABLE", 503)
    result = project_receipt(workspace, {"kind": "review", "key": payload["operationKey"]})
    items = [
        r
        for r in workspace.get("reviews", [])
        if isinstance(r, dict) and r.get("id") == result["operationReceipt"]["reviewId"]
    ]
    if len(items) != 1 or any(items[0].get(key) != payload[key] for key in ("summary", "actions")):
        raise DomainError("PROJECT_REVIEW_RECEIPT_UNAVAILABLE", 503)
    return {**result, "review": items[0]}


def register_project_review(registry, database, settings):
    async def review(args, binding):
        pid = await bound_project(database, binding)
        payload = review_payload(args, binding)
        current = await operation(settings, pid, "show")
        if (
            not current
            or current.get("projectId") != pid
            or (current.get("projectFiles") or {}).get("operationReceiptsSupported") is not True
        ):
            raise DomainError("PROJECT_REVIEW_RECEIPTS_UNAVAILABLE", 503)
        result = await operation(settings, pid, "review", payload)
        return review_receipt(result, pid, payload)

    registry.add(
        Tool(
            "project_okr_review",
            "Save one evidence-based review in this original Main's bound project. Read project_okr_context first; "
            "pass its actual revision, summary and optional actions. The host fixes project identity and one "
            "review key for this original turn. Changed content conflicts; a retry keeps the original receipt. "
            "Never write placeholder/test content to discover fields. Saved review is not publication or goal completion.",
            object_schema(review_fields(), ["revision", "summary"]),
            review,
            main=True,
            effect="write",
        )
    )
