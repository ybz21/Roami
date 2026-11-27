"""Compact facts from a project's confirmed Connector batch ledger."""

import re

from roami_agent.protocol.errors import DomainError


def connector_batch_receipt(workspace, batch_id):
    if not isinstance(batch_id, str) or not re.fullmatch(r"[a-f0-9]{32}", batch_id):
        raise DomainError("INVALID_CONNECTOR_BATCH_ID")
    if (
        not isinstance(workspace, dict)
        or not isinstance(workspace.get("projectId"), str)
        or not workspace["projectId"]
        or type(workspace.get("revision")) is not int
        or workspace["revision"] < 0
        or not isinstance(workspace.get("connectorBatches", []), list)
        or any(not isinstance(item, dict) for item in workspace.get("connectorBatches", []))
    ):
        raise DomainError("CONNECTOR_BATCH_RECEIPT_UNAVAILABLE", 503)
    matches = [
        item
        for item in workspace.get("connectorBatches", [])
        if isinstance(item, dict) and item.get("id") == batch_id
    ]
    result = {
        "projectId": workspace["projectId"],
        "revision": workspace["revision"],
        "batchId": batch_id,
    }
    if not matches:
        return {**result, "status": "not_found"}
    if len(matches) != 1:
        raise DomainError("CONNECTOR_BATCH_RECEIPT_UNAVAILABLE", 503)
    receipt = matches[0]
    fields = (
        "id",
        "connectorId",
        "sourceIdentity",
        "requestSha256",
        "packageSha256",
        "revision",
        "publishedAt",
        "capturedAt",
        "date",
        "windowStart",
        "windowEnd",
        "observationIds",
    )
    if (
        any(
            not isinstance(receipt.get(key), str) or not receipt[key]
            for key in fields
            if key not in {"revision", "observationIds"}
        )
        or any(
            not re.fullmatch(r"[a-f0-9]{64}", receipt[key])
            for key in ("requestSha256", "packageSha256")
        )
        or type(receipt.get("revision")) is not int
        or not 1 <= receipt["revision"] <= workspace["revision"]
        or not isinstance(receipt.get("observationIds"), list)
        or not receipt["observationIds"]
        or len(receipt["observationIds"]) > 64
        or any(not isinstance(item, str) or not item for item in receipt["observationIds"])
        or len(set(receipt["observationIds"])) != len(receipt["observationIds"])
    ):
        raise DomainError("CONNECTOR_BATCH_RECEIPT_UNAVAILABLE", 503)
    return {
        **result,
        "status": "confirmed",
        "receipt": {
            key: list(receipt[key]) if key == "observationIds" else receipt[key] for key in fields
        },
    }
