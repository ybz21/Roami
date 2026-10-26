"""Keep each declared user outcome visible until it has a concrete disposition."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
from roami_agent.protocol.tools import object_schema
from roami_agent.storage.database import event, row
from roami_agent.storage.task_handoff import accepted_handoffs


def coverage_schema():
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": 24,
        "description": "All user outcomes. current=this handoff; delegated needs accepted taskId; answered=delivered.",
        "items": object_schema(
            {
                "quote": {"type": "string", "minLength": 1, "maxLength": 8000},
                "status": {
                    "type": "string",
                    "enum": ["pending", "answered", "current", "delegated", "blocked"],
                },
                "taskId": {"type": "string", "minLength": 1},
                "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
            },
            ["quote", "status"],
        ),
    }


def latest_coverage(db, turn_id):
    prefix = "request.coverage:" + str(turn_id) + ":"
    result = row(
        db,
        "SELECT payload_json FROM events WHERE event_key>=? AND event_key<? "
        "AND turn_id=? AND kind='request.coverage' ORDER BY id DESC LIMIT 1",
        (prefix, prefix + "\uffff", turn_id),
    )
    return json.loads(result["payload_json"])["outcomes"] if result else []


def check_coverage(db, binding, args, *, handoff=False):
    turn = row(db, "SELECT trigger_kind FROM turns WHERE id=?", (binding["turnId"],))
    if turn and turn["trigger_kind"] == "completion":
        return None
    previous = latest_coverage(db, binding["turnId"])
    outcomes = args.get("requestCoverage")
    if outcomes is None:
        if previous:
            raise DomainError("REQUEST_COVERAGE_REQUIRED")
        return None
    source = row(
        db,
        "SELECT m.content_json FROM messages m JOIN conversations c ON c.id=m.conversation_id "
        "JOIN turns t ON t.id=m.turn_id WHERE m.turn_id=? AND m.role='user' "
        "AND c.owner_id=? AND c.id=? AND m.deleted_ms IS NULL AND c.deleted_ms IS NULL "
        "AND t.state='running' ORDER BY m.seq LIMIT 1",
        (binding["turnId"], binding["owner"], binding["conversation"]),
    )
    if not source:
        raise DomainError("REQUEST_COVERAGE_SOURCE_REQUIRED")
    text = json.loads(source["content_json"]).get("text", "")
    quotes = [item["quote"] for item in outcomes]
    if len(set(quotes)) != len(quotes) or any(not q.strip() or q not in text for q in quotes):
        raise DomainError("REQUEST_COVERAGE_SOURCE_REQUIRED")
    if any(item["quote"] not in quotes for item in previous):
        raise DomainError("REQUEST_OUTCOME_DROPPED")
    accepted = accepted_handoffs(db, binding["turnId"])
    dispatched = {
        item["quote"]: item["taskId"] for item in previous if item["status"] == "delegated"
    }
    for item in outcomes:
        status = item["status"]
        if item["quote"] in dispatched and (
            status != "delegated" or item.get("taskId") != dispatched[item["quote"]]
        ):
            raise DomainError("TASK_ALREADY_HANDED_OFF", 409)
        if status == "delegated" and item.get("taskId") not in accepted:
            raise DomainError("REQUEST_HANDOFF_REQUIRED")
        if status == "current" and not handoff:
            raise DomainError("REQUEST_HANDOFF_REQUIRED")
        if status == "blocked" and not item.get("reason", "").strip():
            raise DomainError("REQUEST_BLOCKER_REQUIRED")
    if (not handoff or args.get("requestComplete")) and any(
        item["status"] == "pending" for item in outcomes
    ):
        raise DomainError("REQUEST_OUTCOMES_PENDING")
    if handoff and not any(item["status"] == "current" for item in outcomes):
        raise DomainError("REQUEST_HANDOFF_REQUIRED")
    if handoff and sum(item["status"] == "current" for item in outcomes) != 1:
        raise DomainError("REQUEST_HANDOFF_SCOPE_REQUIRED")
    return outcomes


def record_coverage(db, binding, outcomes, receipt=None):
    if outcomes is None:
        return
    if receipt is not None and not receipt.get("acceptedOnly"):
        return
    updated = [
        {"quote": item["quote"], "status": "delegated", "taskId": receipt["taskId"]}
        if item["status"] == "current"
        else item
        for item in outcomes
    ]
    event(
        db,
        binding["conversation"],
        "request.coverage",
        {"outcomes": updated},
        turn_id=binding["turnId"],
        key="request.coverage:" + binding["turnId"] + ":" + identity(),
    )
