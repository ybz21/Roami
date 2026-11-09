import json

from test_swarm_main_verification import read, verify
from test_swarm_main_verification import review_case as review_case_fixture

review_case = review_case_fixture


async def test_overlong_unicode_line_can_be_read_and_independently_verified(review_case):
    runtime, turn, binding, args, _ = review_case
    body = json.dumps({"records": "真实数据与来源" * 15000}, ensure_ascii=False).encode()
    artifact = await runtime.artifacts.put(
        "alice",
        body,
        mime_type="application/json",
        name="context.json",
        task_id=args["taskId"],
        metadata={"runId": args["runId"]},
    )
    args = {**args, "artifactIds": [artifact["id"]]}
    page = await read(runtime, turn, binding, artifact)
    assert page["truncated"] and page["hasMore"]
    assert page["nextRead"] == {"offset": 0, "limit": 16000}
    assert (await verify(runtime, turn, binding, args))["error"] == "SWARM_ARTIFACT_REVIEW_REQUIRED"
    chunks = []
    while page["nextRead"] is not None:
        page = await read(runtime, turn, binding, artifact, **page["nextRead"])
        assert page["paginationUnit"] == "bytes" and page["encoding"] == "utf-8"
        assert "\ufffd" not in page["text"]
        chunks.append(page["text"].encode())
    assert b"".join(chunks) == body
    assert (await verify(runtime, turn, binding, args))["state"] == "succeeded"
