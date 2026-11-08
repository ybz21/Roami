import pytest
from test_main_file_image_inputs import main_read as main_read_fixture
from test_publication_text_evidence import text_fixture

from roami_agent.dispatch.publication_prompt_review import PublicationPromptReview
from roami_agent.protocol.errors import DomainError
from roami_agent.replies.source_review import SourceReplyReview

main_read = main_read_fixture


async def fixture(value):
    runtime, turn, binding, required = await text_fixture(value, pages=((1, 1), (2, 2)))
    runtime.reply_review = SourceReplyReview(runtime.db, lambda: None)
    plan, prompt = await runtime.loop.context.build(turn, "Review exact text.", [], None)
    runtime.reply_review.observe_context(turn, prompt, source_ids=plan["modelSourceMessageIds"])
    return runtime, turn, binding, required


async def test_complete_reads_survive_real_prompt_builder(main_read):
    runtime, _, binding, required = await fixture(main_read)
    proof = await PublicationPromptReview(
        runtime.db, runtime.artifacts, runtime.reply_review
    ).inspect(binding, required)
    assert len(proof[0]["reads"]) == 2


@pytest.mark.parametrize(
    "fault", ["drop", "drop_one", "clip", "metadata", "old_lease", "forgot_context"]
)
async def test_tools_in_database_do_not_prove_actual_model_input(main_read, fault):
    runtime, turn, binding, required = await fixture(main_read)
    context = runtime.reply_review.contexts[turn["id"]]
    if fault == "drop":
        context["messages"] = [m for m in context["messages"] if m["role"] != "tool"]
    elif fault == "drop_one":
        index = next(i for i, m in enumerate(context["messages"]) if m["role"] == "tool")
        context["messages"].pop(index)
    elif fault in {"clip", "metadata"}:
        for message in context["messages"]:
            if message["role"] == "tool":
                message["content"] = (
                    message["content"][:40] if fault == "clip" else "artifact metadata only"
                )
    elif fault == "old_lease":
        context["epoch"] -= 1
    else:
        runtime.reply_review.forget_turn(turn)
    with pytest.raises(DomainError):
        await PublicationPromptReview(runtime.db, runtime.artifacts, runtime.reply_review).inspect(
            binding, required
        )


async def test_context_replaced_during_blob_verification_is_not_approval(main_read):
    runtime, turn, binding, required = await fixture(main_read)
    original = runtime.artifacts.verified_path
    context = runtime.reply_review.contexts[turn["id"]]

    async def replace(*args):
        result = await original(*args)
        runtime.reply_review.observe_context(
            turn, context["messages"], source_ids=context["source_ids"]
        )
        return result

    runtime.artifacts.verified_path = replace
    with pytest.raises(DomainError, match="PUBLICATION_PROMPT_REVIEW_CHANGED"):
        await PublicationPromptReview(runtime.db, runtime.artifacts, runtime.reply_review).inspect(
            binding, required
        )


async def test_missing_host_model_context_cannot_fall_back_to_tool_receipts(main_read):
    runtime, _, binding, required = await fixture(main_read)
    with pytest.raises(DomainError, match="PUBLICATION_MODEL_CONTEXT_UNAVAILABLE"):
        await PublicationPromptReview(runtime.db, runtime.artifacts, None).inspect(
            binding, required
        )
