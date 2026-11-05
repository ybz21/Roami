"""Resolve the ten-case diagnostic profile from its frozen selected suite."""

from roami_agent.improvement.domain.contracts import require

LIGHT_CASE_IDS = (
    "CODE-01",
    "QUANT-01",
    "DOC-05",
    "DEMO-01",
    "NEWS-01",
    "MECH-MR01",
    "MECH-CT01",
    "MECH-TL01",
    "MECH-MB01",
)


def default_diagnostic_cases(suite):
    finance = sorted(
        case["id"]
        for case in suite["cases"]
        if case["layer"] == "public_component"
        and case.get("origin", {}).get("benchmark") == "finqa"
    )
    require(bool(finance), "RSI_CASE_NOT_FOUND")
    return [*LIGHT_CASE_IDS[:5], finance[0], *LIGHT_CASE_IDS[5:]]
