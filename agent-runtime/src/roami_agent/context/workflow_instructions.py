"""Runtime workflow guidance also applies to persisted role instructions."""

from roami_agent.protocol.serialization import encoded


def workflow_instructions(instructions, skills):
    if not skills:
        return instructions
    return instructions + (
        "\nInstalled optional workflows (availability metadata): "
        + encoded(skills)
        + ". For a request covered by one, read its instructions before choosing operations. "
        "Use its supported workflow and scripts; use other capabilities for unsupported work "
        "or explicit user choices."
    )
