"""Delivery bodies stay out of durable receipts without dropping task evidence."""

import pytest

from roami_agent.protocol.delivery_receipts import delivery_output, delivery_receipt


@pytest.mark.parametrize("name", ["reply", "task_reply", "task_queue_reply"])
def test_delivery_retains_evidence_without_echoing_body(name):
    value = {"reply": "long answer", "tasks": [{"id": "task-1", "state": "running"}]}
    assert delivery_receipt(name, value) == {"accepted": True, "tasks": value["tasks"]}
    assert value["reply"] == "long answer"


def test_question_receipt_and_activity_do_not_repeat_question():
    value = {"question": {"prompt": "Choose", "options": ["A", "B"]}, "state": "waiting_user"}
    assert delivery_receipt("ask_user", value) == {"state": "waiting_user"}
    assert delivery_output("ask_user", "succeeded", value) is None
    assert delivery_output("reply", "succeeded", {"accepted": True}) is None


def test_errors_and_read_results_are_preserved():
    error = {"error": "REPLY_LANGUAGE_MISMATCH", "reply": "rejected"}
    assert delivery_receipt("reply", error) == error
    assert delivery_output("reply", "failed", error) == error
    result = {"reply": "external report", "state": "running"}
    assert delivery_receipt("session_dispatch_status", result) == result


def test_legacy_history_projects_receipts_without_rewriting_transcript():
    from roami_agent.context.projection import model_messages
    from roami_agent.protocol.serialization import encoded

    call = {"id": "call-1", "function": {"name": "reply", "arguments": '{"text":"answer"}'}}
    transcript = [
        {
            "id": "a",
            "turn_id": "turn",
            "role": "assistant",
            "status": "completed",
            "content_json": encoded({"text": "", "tool_calls": [call]}),
        },
        {
            "id": "b",
            "turn_id": "turn",
            "role": "tool",
            "status": "completed",
            "content_json": encoded(
                {"text": encoded({"reply": "answer"}), "tool_call_id": "call-1"}
            ),
        },
    ]
    assert model_messages(transcript)[1]["content"] == encoded({"accepted": True})
    assert "answer" in transcript[1]["content_json"]
