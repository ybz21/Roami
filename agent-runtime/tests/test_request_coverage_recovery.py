"""A rejected quote must not direct Main to send unsupported handoff arguments."""

import pytest
from test_assignment_recovery import active_turn, call
from test_routing_policy import request, setup
from test_task_delivery_benchmark import admit, mark

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import rows
from roami_agent.storage.request_coverage import latest_coverage
from roami_agent.storage.request_quotes import source_quote

SOURCE = "Read `/workspace/input.csv` and save `/workspace/result.json`; preserve the column names."


@pytest.mark.parametrize(
    ("text", "quote", "expected"),
    [
        (
            "prefix: Read\n  `input.csv` and\tsave it. tail",
            "Read `input.csv` and save it.",
            "Read\n  `input.csv` and\tsave it.",
        ),
        ("\n\nRead\nthis file\n", "Read this file", "Read\nthis file"),
        ("Read\u00a0this\u3000file", "Read this file", "Read\u00a0this\u3000file"),
        (SOURCE, SOURCE.replace(";", ","), None),
        (SOURCE, SOURCE.replace("`", ""), None),
        (SOURCE, SOURCE.replace("input.csv", "other.csv"), None),
    ],
)
def test_whitespace_alignment_preserves_the_source_and_rejects_content_changes(
    text, quote, expected
):
    assert source_quote(text, quote) == expected


def test_existing_inventory_keeps_its_original_source_span():
    text = "Read this file. Read\nthis file."
    previous = "Read\nthis file."
    assert source_quote(text, "Read this file.", [previous]) == previous


async def test_aligned_span_keeps_the_existing_quote_length_limit(store):
    original = "Read" + " " * 8000 + "this file."
    runtime, _, _, tools, binding = await setup(store, user=original)
    try:
        args = {
            **request("bounded"),
            "requestCoverage": [{"quote": "Read this file.", "status": "current"}],
        }
        with pytest.raises(DomainError, match="REQUEST_COVERAGE_SOURCE_REQUIRED"):
            await tools.invoke(call("long-span", "delegate", args), "main", binding)
        assert not await store.call(lambda db: latest_coverage(db, binding["turnId"]))
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


@pytest.mark.parametrize("field", ["owner", "conversation"])
async def test_whitespace_alignment_cannot_read_another_owner_or_conversation(store, field):
    original = SOURCE.replace(" and ", " and\n  ")
    runtime, _, _, tools, binding = await setup(store, user=original)
    try:
        other = {**binding, field: "other"}
        args = {**request("bounded"), "requestCoverage": [{"quote": SOURCE, "status": "current"}]}
        with pytest.raises(DomainError, match="REQUEST_COVERAGE_SOURCE_REQUIRED"):
            await tools.invoke(call("wrong-owner", "delegate", args), "main", other)
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


async def test_normalized_quote_is_persisted_as_original_and_cannot_duplicate_work(store):
    original = SOURCE.replace(" and ", " and\n  ")
    runtime, _, _, tools, binding = await setup(store, user=original)
    try:
        args = {**request("bounded"), "requestCoverage": [{"quote": SOURCE, "status": "current"}]}
        accepted = await tools.invoke(call("first", "delegate", args), "main", binding)
        assert accepted["acceptedOnly"] is True
        outcomes = await store.call(lambda db: latest_coverage(db, binding["turnId"]))
        assert outcomes[0]["quote"] == original and outcomes[0]["status"] == "delegated"
        assert args["requestCoverage"][0]["quote"] == SOURCE
        with pytest.raises(DomainError, match="TASK_ALREADY_HANDED_OFF"):
            await tools.invoke(call("second", "delegate", args), "main", binding)
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


async def test_two_whitespace_forms_cannot_declare_two_outcomes(store):
    original = SOURCE.replace(" and ", " and\n  ")
    runtime, _, _, tools, binding = await setup(store, user=original)
    try:
        args = {
            **request("bounded"),
            "requestCoverage": [
                {"quote": SOURCE, "status": "current"},
                {"quote": original, "status": "pending"},
            ],
        }
        with pytest.raises(DomainError, match="REQUEST_COVERAGE_SOURCE_REQUIRED"):
            await tools.invoke(call("duplicate", "delegate", args), "main", binding)
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


async def test_continuation_aligns_both_quote_fields_before_source_scope_comparison(store):
    original = SOURCE.replace(" and ", " and\n  ")
    runtime, _, _, tools, binding = await setup(store, user=original)
    try:
        task = await admit(
            runtime,
            binding,
            "Original task",
            "seed",
            executor="codex",
            target={"kind": "project", "projectId": "p"},
        )
        await mark(runtime, task)
        accepted = await tools.invoke(
            call(
                "steer",
                "task_steer",
                {
                    "taskId": task["id"],
                    "revision": 1,
                    "text": "Additional processing",
                    "sourceQuote": SOURCE,
                    "requestCoverage": [{"quote": original, "status": "current"}],
                },
            ),
            "main",
            binding,
        )
        assert accepted["acceptedOnly"] is True
        outcomes = await store.call(lambda db: latest_coverage(db, binding["turnId"]))
        assert outcomes[0]["quote"] == original
        assert outcomes[0]["taskId"] == task["id"]
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize("quote", [SOURCE.replace("`", ""), SOURCE.replace(";", ",")])
async def test_delegate_quote_recovery_accepts_exact_source_without_an_extra_field(store, quote):
    runtime, _, _, tools, binding = await setup(store, user=SOURCE)
    runtime.gateway.tools = tools
    try:
        turn = await active_turn(store, binding)
        args = {**request("bounded"), "requestCoverage": [{"quote": quote, "status": "current"}]}
        rejected = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("bad", "delegate", args), "main", binding
        )
        assert rejected["error"] == "REQUEST_COVERAGE_SOURCE_REQUIRED"
        assert rejected["executionStarted"] is False
        assert "sourceQuote" not in rejected["recovery"]
        assert "requestCoverage[].quote" in rejected["recovery"]
        assert not await runtime.tasks.list("alice")
        args["requestCoverage"][0]["quote"] = SOURCE
        binding["toolCallId"] = "fixed"
        fixed = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("fixed", "delegate", args), "main", binding
        )
        assert fixed["acceptedOnly"] is True
        assert len(await runtime.tasks.list("alice")) == 1
        with pytest.raises(DomainError, match="TASK_ALREADY_HANDED_OFF"):
            await tools.invoke(call("repeat", "delegate", args), "main", binding)
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize("operation", ["reply", "task_steer"])
async def test_recovery_matches_reply_and_continuation_contracts(store, operation):
    runtime, _, _, tools, binding = await setup(store, user=SOURCE)
    runtime.gateway.tools = tools
    try:
        turn = await active_turn(store, binding)
        args = {
            "text": "Requested correction",
            "requestCoverage": [{"quote": "invented", "status": "current"}],
        }
        if operation == "task_steer":
            args.update(taskId="not-looked-up", revision=1, requestComplete=False)
        value = await runtime.gateway.invoke(
            turn, binding["assistantMessageId"], call("bad", operation, args), "main", binding
        )
        assert value["error"] == "REQUEST_COVERAGE_SOURCE_REQUIRED"
        if operation == "task_steer":
            assert "task_steer.sourceQuote" in value["recovery"]
        else:
            assert "sourceQuote" not in value["recovery"]
            assert "no pending or current" in value["recovery"]
        assert not await store.call(
            lambda db: rows(db, "SELECT * FROM jobs WHERE kind='task.steer'")
        )
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()
