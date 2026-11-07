"""Bind project write identity to the actual batch, never a model call or fresh CAS."""

import hashlib
import json
import re
from copy import deepcopy

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import rows


def project_write(db, value, name, args, binding):
    prefix = "coordination:" + value["id"] + ":"
    if name == "swarm_memory_write":
        return args, {**binding, "coordinationMemoryKey": prefix + "memory"}
    if name != "swarm_project_update":
        return args, binding
    payload = args["payload"]
    if "operationKey" in payload:
        raise DomainError("SWARM_COORDINATION_OPERATION_KEY_RESERVED", 409)
    if args["operation"] == "record" and "batch" in payload:
        # Connector batches already freeze their own source/window identity and request digest.
        payload = original_connector_payload(db, value, payload)
        return {**args, "payload": payload}, {
            **binding,
            "coordinationProjectWrite": {
                "kind": "connector_batch",
                "id": payload["batch"].get("id") if isinstance(payload["batch"], dict) else None,
            },
        }
    suffix = "review"
    if args["operation"] == "record":
        metric, date = payload.get("metricId"), payload.get("date")
        if not isinstance(metric, str) or not metric or not isinstance(date, str) or not date:
            raise DomainError("INVALID_TOOL_ARGUMENTS")
        suffix = "record:" + hashlib.sha256(encoded([metric, date]).encode()).hexdigest()
    return {**args, "payload": {**payload, "operationKey": prefix + suffix}}, {
        **binding,
        "coordinationProjectWrite": {
            "kind": "review" if args["operation"] == "review" else "observation",
            "key": prefix + suffix,
        },
    }


def project_receipt(workspace, expected):
    receipt = (workspace.get("projectFiles") or {}).get("operationReceipt")
    if expected["kind"] == "connector_batch":
        receipts = [
            item
            for item in workspace.get("connectorBatches", [])
            if item.get("id") == expected["id"]
        ]
        if not isinstance(expected["id"], str) or len(receipts) != 1:
            raise DomainError("SWARM_PROJECT_RECEIPT_UNAVAILABLE", 503)
        receipt = receipts[0]
    elif (
        not isinstance(receipt, dict)
        or receipt.get("key") != expected["key"]
        or receipt.get("kind") != expected["kind"]
    ):
        raise DomainError("SWARM_PROJECT_RECEIPT_UNAVAILABLE", 503)
    if (
        not isinstance(receipt, dict)
        or not isinstance(receipt.get("requestSha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", receipt["requestSha256"])
    ):
        raise DomainError("SWARM_PROJECT_RECEIPT_UNAVAILABLE", 503)
    if expected["kind"] != "connector_batch":
        identity_key = "reviewId" if expected["kind"] == "review" else "observationId"
        if any(
            not isinstance(receipt.get(key), str) or not receipt[key]
            for key in (identity_key, "recordedAt")
        ):
            raise DomainError("SWARM_PROJECT_RECEIPT_UNAVAILABLE", 503)
    return {
        "projectId": workspace.get("projectId"),
        "revision": workspace["revision"],
        "connectorBatchReceipt"
        if expected["kind"] == "connector_batch"
        else "operationReceipt": receipt,
    }


def connector_slot(payload):
    batch = payload.get("batch")
    fields = ("connectorId", "sourceIdentity", "date", "windowStart", "windowEnd")
    if not isinstance(batch, dict) or any(
        not isinstance(batch.get(key), str) or not batch[key] for key in fields
    ):
        return None
    return tuple(batch[key] for key in fields)


def original_connector_payload(db, value, payload):
    slot = connector_slot(payload)
    if slot is None:
        return payload
    for call in rows(
        db,
        "SELECT x.arguments_json,x.state,native_content(m.content_json) AS result FROM tool_calls x LEFT JOIN messages m ON m.id=x.result_message_id WHERE x.turn_id=? AND x.tool_name='swarm_project_update' AND x.effect='write' ORDER BY x.rowid",
        (value["turn_id"],),
    ):
        if call["state"] == "failed" and call["result"]:
            try:
                result = json.loads(json.loads(call["result"]).get("text", "{}"))
            except (ValueError, TypeError):
                result = {}
            if isinstance(result, dict) and (
                result.get("executionStarted") is False or result.get("error") == "OKR_INVALID"
            ):
                continue
        arguments = json.loads(call["arguments_json"])
        original = arguments.get("payload", {})
        if arguments.get("operation") != "record" or connector_slot(original) != slot:
            continue
        candidate = deepcopy(payload)
        candidate["revision"] = original.get("revision")
        candidate["batch"]["id"] = original["batch"].get("id")
        if candidate != original:
            raise DomainError("SWARM_COORDINATION_CONNECTOR_CHANGED", 409)
        # The Go batch digest includes revision; replay the exact first body after uncertain writes.
        return original
    return payload
