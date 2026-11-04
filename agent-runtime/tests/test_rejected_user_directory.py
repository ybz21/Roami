"""Planner path correction cannot discard a rejected user destination."""

import json

import pytest
from test_assignment_recovery import active_turn, call
from test_routing_policy import setup

from roami_agent.storage.database import row


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("user_selected", [False, True])
async def test_rejected_directory_keeps_user_destination_and_allows_planner_correction(
    store, tmp_path, compact, user_selected
):
    missing = str(tmp_path / "missing destination")
    user = (
        "Save a report to " + missing
        if user_selected
        else "Save a report in a new private task directory"
    )
    runtime, _, _, _, binding = await setup(store, user=user)
    try:
        turn = await active_turn(store, binding)
        first = {"goal": "Save the report", "executor": "native"}
        first.update(
            {"directory": missing}
            if compact
            else {"target": {"kind": "new_session", "directory": missing}}
        )
        rejected = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call("rejected", "delegate", first),
            "main",
            dict(binding, toolCallId="rejected"),
        )
        assert rejected["error"] == "EXECUTION_DIRECTORY_UNAVAILABLE"
        fallback = {
            "goal": "Save the same report with changed assistant wording",
            "executor": "native",
        }
        if not compact:
            fallback["target"] = {"kind": "new_session"}
        result = await runtime.gateway.invoke(
            turn,
            binding["assistantMessageId"],
            call("fallback", "delegate", fallback),
            "main",
            dict(binding, toolCallId="fallback"),
        )
        if user_selected:
            assert result.get("error") == "TASK_TARGET_REVIEW_REQUIRED"
            assert not await runtime.tasks.list("alice")
            await store.call(
                lambda db: db.execute(
                    "UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)
                ),
                write=True,
            )
            correction = await runtime.conversations.accept(
                "alice",
                binding["conversation"],
                "user-correction",
                "Use a private task directory instead",
            )
            job = await store.call(
                lambda db: row(
                    db, "SELECT * FROM jobs WHERE aggregate_id=?", (correction["turnId"],)
                )
            )
            new_turn = await runtime.mailbox.claim(job)
            mid = await runtime.journal.start(new_turn)
            bound = dict(
                binding,
                turnId=new_turn["id"],
                originMessageId=correction["messageId"],
                assistantMessageId=mid,
                toolCallId="approved",
            )
            recovered = await runtime.gateway.invoke(
                new_turn, mid, call("approved", "delegate", fallback), "main", bound
            )
            assert recovered["acceptedOnly"] is True
        else:
            assert result["acceptedOnly"] is True
            task = (await runtime.tasks.list("alice"))[0]
            assert json.loads(task["intent_json"])["target"] == {"kind": "new_session"}
    finally:
        await runtime.close()
