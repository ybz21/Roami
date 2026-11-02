"""Keep model request correlation separate from private response content."""

import re

from roami_agent.protocol.errors import DomainError

GATEWAY_EXTENSION = "roami_go_gateway"
BRIDGE_EXTENSION = "roami_receipt_bridge"
REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,200}")
CALL_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def response_receipt(response, attempt):
    receipt = {"phase": "headers", "attempt": attempt, "httpStatus": response.status_code}
    request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
    if request_id and REQUEST_ID.fullmatch(request_id):
        receipt["requestId"] = request_id
    call_id = response.headers.get("x-roami-model-call")
    if (
        response.extensions.get(GATEWAY_EXTENSION) is True
        and call_id
        and CALL_ID.fullmatch(call_id)
    ):
        receipt["gatewayCallId"] = call_id
    return receipt


def forwarded_receipt(value):
    if (
        not isinstance(value, dict)
        or value.get("phase") != "headers"
        or type(value.get("attempt")) is not int
        or value["attempt"] < 1
    ):
        return None
    receipt = {"phase": "headers", "attempt": value["attempt"]}
    for key, pattern in (("requestId", REQUEST_ID), ("gatewayCallId", CALL_ID)):
        item = value.get(key)
        if isinstance(item, str) and pattern.fullmatch(item):
            receipt[key] = item
    status = value.get("httpStatus")
    if type(status) is int and 100 <= status <= 599:
        receipt["httpStatus"] = status
    return receipt


def relayed_receipt(value, attempt):
    receipt = forwarded_receipt(value)
    if receipt is None:
        return None
    return {
        **receipt,
        "phase": "upstream_headers",
        "attempt": attempt,
        "upstreamAttempt": receipt["attempt"],
    }


def usage_receipt(value):
    if (
        not isinstance(value, dict)
        or type(value.get("requestAttempts")) is not int
        or value["requestAttempts"] < 1
        or type(value.get("retryUsageKnown")) is not bool
    ):
        raise DomainError("MODEL_USAGE_INVALID", 502)
    return {key: value[key] for key in ("requestAttempts", "retryUsageKnown")}
