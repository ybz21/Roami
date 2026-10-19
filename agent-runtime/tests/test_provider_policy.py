"""Provider failures cannot replay visible text, leak credentials or cross cache identities."""

import asyncio
import json

import httpx
import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import model_endpoint
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.providers.request_policy import normalized_usage
from roami_agent.server.configuration import Settings


def answer(text="answer", usage=None):
    chunks = [{"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}]
    if usage is not None:
        chunks.append({"choices": [], "usage": usage})
    return "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"


async def test_retry_after_is_respected_before_output_and_usage_keeps_retry_unknown():
    requests, sleeps = [], []

    async def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                503, headers={"Retry-After": "0.75"}, text="private provider diagnostics"
            )
        return httpx.Response(200, text=answer(usage={"prompt_tokens": 11, "completion_tokens": 2}))

    async def sleep(delay):
        sleeps.append(delay)

    model = ChatCompletions(
        "https://provider.invalid/v1",
        "fixture",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        sleep=sleep,
    )
    try:
        result = [part async for part in model.stream([], [])]
        assert len(requests) == 2 and sleeps == [0.75]
        assert [part.value for part in result if part.kind == "text"] == ["answer"]
        usage = next(part.value for part in result if part.kind == "usage")
        assert usage["inputTokens"] == 11 and usage["requestAttempts"] == 2
        assert usage["retryUsageKnown"] is False
        assert usage["cacheReadTokens"] is None and usage["cacheWriteTokens"] is None
    finally:
        await model.close()


async def test_visible_partial_output_is_never_retried_after_transport_failure():
    calls = 0

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise httpx.ReadError("private endpoint diagnostics")

    async def handle(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=BrokenStream())

    model = ChatCompletions(
        "https://provider.invalid/v1",
        "fixture",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    parts = []
    try:
        with pytest.raises(DomainError, match="^MODEL_TRANSPORT_FAILED$"):
            async for part in model.stream([], []):
                parts.append(part)
        assert calls == 1 and [part.value for part in parts if part.kind == "text"] == ["partial"]
        assert [part.value["phase"] for part in parts if part.kind == "telemetry"] == [
            "request",
            "headers",
            "first_delta",
        ]
    finally:
        await model.close()


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "MODEL_HTTP_401"),
        (400, "MODEL_HTTP_400"),
        (307, "MODEL_REDIRECT_BLOCKED"),
        (503, "MODEL_RETRY_DEADLINE"),
    ],
)
async def test_auth_redirects_and_retry_delays_do_not_create_unbounded_requests(status, expected):
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Retry-After": "900", "Location": "https://elsewhere.invalid/v1"},
            text="sensitive response",
        )

    model = ChatCompletions(
        "https://provider.invalid/v1",
        "fixture",
        "private-test-key",
        timeout=1,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True),
    )
    try:
        with pytest.raises(DomainError, match="^" + expected + "$"):
            _ = [part async for part in model.stream([], [])]
        assert len(calls) == 1 and calls[0].url.host == "provider.invalid"
    finally:
        await model.close()


async def test_retry_limit_and_cancellation_during_backoff():
    calls = 0
    sleeping = asyncio.Event()

    async def handle(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    async def sleep(delay):
        sleeping.set()
        await asyncio.Event().wait()

    model = ChatCompletions(
        "https://provider.invalid/v1",
        "fixture",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        sleep=sleep,
    )

    async def consume():
        return [part async for part in model.stream([], [])]

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(sleeping.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == 1
    finally:
        await model.close()


@pytest.mark.parametrize("retries", [0, 2])
async def test_transient_failures_stop_at_the_configured_attempt_limit(retries):
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(500, text="private diagnostics")

    async def sleep(delay):
        pass

    model = ChatCompletions(
        "https://provider.invalid/v1",
        "fixture",
        max_retries=retries,
        sleep=sleep,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        with pytest.raises(DomainError, match="^MODEL_HTTP_500$"):
            _ = [part async for part in model.stream([], [])]
        assert len(calls) == retries + 1
    finally:
        await model.close()


async def test_cache_configuration_is_opt_in_and_changes_with_route_and_tools():
    bodies = []

    async def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, text=answer())

    def client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handle))

    capabilities = {"version": "fixture-v1", "prompt_cache_key": True, "prompt_cache_options": True}
    default = ChatCompletions("https://one.invalid/v1", "model", client=client())
    configured = ChatCompletions(
        "https://one.invalid/v1",
        "model",
        client=client(),
        capabilities=capabilities,
        cache={"namespace": "instance", "mode": "implicit", "ttl": "30m"},
    )
    other = ChatCompletions(
        "https://two.invalid/v1",
        "model",
        client=client(),
        capabilities=capabilities,
        cache={"namespace": "instance"},
    )
    try:
        for model, messages, tools in [
            (default, [{"role": "system", "content": "stable"}], []),
            (configured, [{"role": "system", "content": "stable"}], []),
            (
                configured,
                [{"role": "system", "content": "stable"}, {"role": "user", "content": "append"}],
                [],
            ),
            (
                configured,
                [{"role": "system", "content": "stable"}],
                [{"type": "function", "function": {"name": "changed"}}],
            ),
            (other, [{"role": "system", "content": "stable"}], []),
        ]:
            _ = [part async for part in model.stream(messages, tools)]
        assert "prompt_cache_key" not in bodies[0] and "prompt_cache_options" not in bodies[0]
        assert bodies[1]["prompt_cache_options"] == {"mode": "implicit", "ttl": "30m"}
        assert bodies[1]["prompt_cache_key"] == bodies[2]["prompt_cache_key"]
        assert (
            bodies[1]["prompt_cache_key"]
            != bodies[3]["prompt_cache_key"]
            != bodies[4]["prompt_cache_key"]
        )
        assert configured.provider_key != other.provider_key
        assert configured.settings_hash != other.settings_hash
    finally:
        for model in [default, configured, other]:
            await model.close()


async def test_explicit_cache_marks_only_the_system_prefix_without_mutating_context():
    bodies = []

    async def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, text=answer())

    model = ChatCompletions(
        "https://provider.invalid/v1",
        "fixture",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        capabilities={"prompt_cache_options": True},
        cache={"mode": "explicit", "ttl": "30m"},
    )
    messages = [
        {"role": "system", "content": "stable instructions"},
        {"role": "user", "content": "current question"},
    ]
    original = json.loads(json.dumps(messages))
    try:
        _ = [part async for part in model.stream(messages, [])]
        assert messages == original
        marked = bodies[0]["messages"][0]["content"]
        assert marked[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
        assert bodies[0]["messages"][1] == messages[1]
        with pytest.raises(DomainError, match="MODEL_CACHE_PREFIX_REQUIRED"):
            _ = [part async for part in model.stream(messages[1:], [])]
        assert len(bodies) == 1
    finally:
        await model.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": 1},
        {"choices": [False]},
        {"choices": [{"delta": {"tool_calls": [{"index": -1}]}}]},
        {"choices": [{"delta": {"content": ["unsupported"]}}]},
    ],
)
async def test_malformed_provider_events_fail_as_domain_errors_without_retry(payload):
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(200, text="data: " + json.dumps(payload) + "\n\n")

    model = ChatCompletions(
        "https://provider.invalid/v1",
        "fixture",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        with pytest.raises(DomainError, match="MODEL_STREAM_INVALID"):
            _ = [part async for part in model.stream([], [])]
        assert len(calls) == 1
    finally:
        await model.close()


def test_missing_usage_fields_are_unknown_even_when_other_counts_are_zero():
    usage = normalized_usage(
        {"completion_tokens": 0, "prompt_tokens_details": {"cached_tokens": True}}, 1
    )
    assert usage["outputTokens"] == 0 and usage["inputTokens"] is None
    assert usage["cacheReadTokens"] is None and usage["knownFields"] == ["outputTokens"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:80@remote.invalid/v1",
        "https://user:password@remote.invalid/v1",
        "https://remote.invalid/v1?key=private",
        "https://remote.invalid/v1#fragment",
        "https://remote.invalid:99999",
        "https://remote.invalid/\npath",
        "http://remote.invalid/v1",
    ],
)
def test_endpoint_validation_rejects_credential_urls_and_nonlocal_plain_http(endpoint):
    with pytest.raises(DomainError):
        model_endpoint(endpoint)


def test_policy_configuration_keeps_existing_private_provider_layout(tmp_path):
    path = tmp_path / "agent.toml"
    path.write_text(
        '[model]\nendpoint="https://provider.invalid/v1/"\nname="fixture"\nkey_env="PRIVATE_ENV_NAME"\nmax_retries=1\n[model.capabilities]\nversion="fixture-v2"\nstream_usage=false\n'
    )
    settings = Settings.load(path)
    assert settings.endpoint == "https://provider.invalid/v1"
    assert settings.key_env == "PRIVATE_ENV_NAME" and settings.model_retries == 1
    assert settings.model_capabilities["version"] == "fixture-v2"
    assert model_endpoint("http://[::1]:8800/v1") == "http://[::1]:8800/v1"
    with pytest.raises(DomainError, match="MODEL_CACHE_CAPABILITY_REQUIRED"):
        ChatCompletions(
            "https://provider.invalid/v1", "fixture", cache={"namespace": "not-verified"}
        )


async def test_prompt_manifests_partition_identical_text_by_endpoint_model_and_capabilities(store):
    from test_runtime import until

    from roami_agent.app import Runtime
    from roami_agent.storage.database import row

    records = []

    async def handle(request):
        return httpx.Response(200, text=answer())

    for endpoint, name, version in [
        ("https://one.invalid/v1", "alpha", "v1"),
        ("https://two.invalid/v1", "alpha", "v1"),
        ("https://one.invalid/v1", "alpha", "v2"),
        ("https://one.invalid/v1", "beta", "v1"),
    ]:
        model = ChatCompletions(
            endpoint,
            name,
            capabilities={"version": version},
            client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        runtime = Runtime(store, model)
        await runtime.start()
        try:
            c = await runtime.conversations.create("alice")
            receipt = await runtime.chat.submit(
                "alice", c["id"], "route:" + str(len(records)), "hello"
            )
            await until(
                store,
                lambda db, tid=receipt["turnId"]: row(
                    db,
                    "SELECT id FROM turns WHERE id=? AND state='completed'",
                    (tid,),
                ),
            )
            manifest = await store.call(
                lambda db, tid=receipt["turnId"]: row(
                    db, "SELECT * FROM prompt_manifests WHERE turn_id=?", (tid,)
                )
            )
            assert manifest["provider_key"] == model.provider_key
            assert json.loads(manifest["parts_json"])["modelSettingsHash"] == model.settings_hash
            assert endpoint not in json.dumps(manifest)
            records.append(manifest)
        finally:
            await runtime.close()
            await model.close()
    assert len({item["prefix_sha256"] for item in records}) == 4
    assert records[0]["provider_key"] == records[2]["provider_key"] == records[3]["provider_key"]
    assert records[0]["provider_key"] != records[1]["provider_key"]
