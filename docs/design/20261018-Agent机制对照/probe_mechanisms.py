import asyncio
import json
import tempfile
from pathlib import Path

import httpx

from roami_agent.app import Runtime
from roami_agent.context.token_estimate import text_tokens
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import Database, row


class ToolModel:
    model = "audit-synthetic"

    def __init__(self, name):
        self.name = name
        self.calls = 0

    async def stream(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            yield ModelEvent(
                "tool",
                {
                    "id": "audit-call",
                    "type": "function",
                    "function": {"name": self.name, "arguments": "{}"},
                },
            )
        else:
            yield ModelEvent("text", "Audit final response")


async def drive(runtime, cid, key, text):
    receipt = await runtime.chat.submit("audit", cid, key, text)
    job = await runtime.db.call(
        lambda d: row(
            d, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (receipt["turnId"],)
        )
    )
    turn = await runtime.mailbox.claim(job)
    error = None
    try:
        await runtime.loop.run(turn, "main")
    except DomainError as exc:
        error = exc.code
    state = await runtime.db.call(
        lambda d: row(d, "SELECT state FROM turns WHERE id=?", (turn["id"],))
    )
    return receipt, error, state["state"]


async def main():
    root = Path(tempfile.mkdtemp(prefix="roami-pi-audit-probes-"))
    root.chmod(0o700)
    db = Database(root / "runtime.db", root, managed=False)
    await db.open()
    proof = []
    try:
        runtime = Runtime(db, ToolModel("unused"))
        c = await runtime.conversations.create("audit")
        body = "测试" * 100
        r = await runtime.conversations.accept("audit", c["id"], "memory-source", body)
        await runtime.memory.save("audit", "长度审计", body, r["messageId"])
        hit = (await runtime.memory.recall("audit", "测试"))["hits"][0]
        proof.append(
            {
                "id": "memory-token-unit",
                "observed": {
                    "reportedTokenEstimate": hit["tokenEstimate"],
                    "piCharacterEstimate": text_tokens(body),
                    "characters": len(body),
                },
                "confirmed": hit["tokenEstimate"] != text_tokens(body),
            }
        )
        await runtime.close()
        for name, kind in [
            ("oversized-write-result", "large"),
            ("write-response-timeout", "timeout"),
            ("oversized-current-tool-round", "read-large"),
        ]:
            writes = []

            async def handler(args, binding, kind=kind, writes=writes):
                if kind != "read-large":
                    writes.append("synthetic in-memory effect")
                if kind == "timeout":
                    raise httpx.ReadTimeout("synthetic response timeout")
                return {"text": "x" * (129000 if kind == "large" else 60000)}

            model = ToolModel("audit_tool")
            runtime = Runtime(
                db, model, settings=Settings(input_budget=10000 if kind == "read-large" else 24000)
            )
            runtime.tools.add(
                Tool(
                    "audit_tool",
                    "Synthetic audit tool",
                    object_schema({}),
                    handler,
                    effect="read" if kind == "read-large" else "write",
                    main=True,
                )
            )
            c = await runtime.conversations.create("audit")
            receipt, error, state = await drive(
                runtime, c["id"], name, "Run the synthetic audit tool"
            )
            tool = await db.call(
                lambda d, receipt=receipt: row(
                    d, "SELECT state FROM tool_calls WHERE turn_id=?", (receipt["turnId"],)
                )
            )
            proof.append(
                {
                    "id": name,
                    "observed": {
                        "syntheticEffects": len(writes),
                        "toolState": tool["state"],
                        "turnState": state,
                        "turnError": error,
                        "modelRequests": model.calls,
                    },
                    "confirmed": (len(writes) == 1 and tool["state"] == "failed")
                    if kind != "read-large"
                    else error == "CONTEXT_TOO_LARGE",
                }
            )
            await runtime.close()
        requests = []

        async def overflow(request):
            requests.append(1)
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "context_length_exceeded",
                        "message": "maximum context length exceeded",
                    }
                },
            )

        provider = ChatCompletions(
            "https://audit.invalid/v1",
            "audit",
            client=httpx.AsyncClient(transport=httpx.MockTransport(overflow)),
        )
        runtime = Runtime(db, provider)
        c = await runtime.conversations.create("audit")
        receipt, error, state = await drive(runtime, c["id"], "overflow", "Small request")
        compact = await db.call(
            lambda d: d.execute(
                "SELECT count(*) FROM jobs WHERE kind='context.compact' AND json_extract(payload_json,'$.conversationId')=?",
                (c["id"],),
            ).fetchone()[0]
        )
        proof.append(
            {
                "id": "provider-context-overflow",
                "observed": {
                    "error": error,
                    "providerRequests": len(requests),
                    "compactionJobs": compact,
                    "turnState": state,
                },
                "confirmed": error == "MODEL_HTTP_400" and compact == 0,
            }
        )
        await runtime.close()
        await provider.close()
        assert all(p["confirmed"] for p in proof)
        print(json.dumps(proof, indent=2))
    finally:
        await db.close()


asyncio.run(main())
