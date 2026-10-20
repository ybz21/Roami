"""Bound completion evidence without changing the persisted executor report."""

from roami_agent.context.token_estimate import text_tokens
from roami_agent.protocol.serialization import encoded


def completion_evidence(completion, *, budget):
    if text_tokens(encoded(completion)) <= budget:
        return completion
    result = completion.get("result", {})
    projection = {
        key: completion[key]
        for key in ["taskId", "taskRevision", "runId", "state"]
        if key in completion
    }
    projection.update(
        evidenceTruncated=True,
        resultRef={
            key: completion[key] for key in ["taskId", "taskRevision", "runId"] if key in completion
        },
    )
    result = result if isinstance(result, dict) else {}
    detail = {
        key: result[key]
        for key in ["outcomeKnown", "inputStopped", "cancellationRequested", "retryable"]
        if type(result.get(key)) is bool
    }
    if result.get("state") in {"succeeded", "failed", "cancelled"}:
        detail["state"] = result["state"]
    if type(result.get("exitCode")) is int and -(2**31) <= result["exitCode"] < 2**31:
        detail["exitCode"] = result["exitCode"]
    for key in ["checks", "blockers", "children", "artifactRefs"]:
        if isinstance(result.get(key), list):
            detail[key + "Count"] = len(result[key])
    artifact_ids = (
        [
            item["id"]
            for item in result.get("artifactRefs", [])[:4]
            if isinstance(item, dict) and isinstance(item.get("id"), str) and len(item["id"]) <= 100
        ]
        if isinstance(result.get("artifactRefs"), list)
        else []
    )
    if artifact_ids:
        detail["artifactIds"] = artifact_ids
    references = (
        [
            {
                "id": item["id"],
                "name": item.get("name", "")[:160],
                "downloadUrl": item["downloadUrl"],
            }
            for item in result.get("artifactRefs", [])[:4]
            if isinstance(item, dict)
            and item.get("id") in artifact_ids
            and isinstance(item.get("name", ""), str)
            and isinstance(item.get("downloadUrl"), str)
            and len(item["downloadUrl"]) <= 2048
        ]
        if isinstance(result.get("artifactRefs"), list)
        else []
    )
    if references:
        detail["artifactRefs"] = references
    summary = result.get("summary", "")
    summary = summary if isinstance(summary, str) else ""
    for limit in [3000, 1500, 750, 300, 100, 0]:
        projection["result"] = dict(detail, summary=summary[:limit])
        if text_tokens(encoded(projection)) <= budget:
            return projection
    projection["result"].pop("artifactRefs", None)
    projection["result"].pop("artifactIds", None)
    return projection
