"""Small deterministic fixtures for checking the harness without a paid provider."""

from roami_agent.improvement.contracts import freeze_suite


def protocol_suite():
    cases = []
    for identifier, values in (("PROTOCOL-FILES-1", [17, 23]), ("PROTOCOL-FILES-2", [0, -7, 19])):
        total = sum(values)
        cases.append(
            {
                "id": identifier,
                "category": "HARNESS",
                "layer": "smoke",
                "split": "development",
                "counts_as_delivery": False,
                "prompt": 'Read input.json and save {"sum": total} in output.json.',
                "files": {"input.json": str(values)},
                "limits": {"seconds": 10, "tokens": 128000, "requests": 8},
                "judge": {"kind": "json", "path": "output.json", "expected": {"sum": total}},
                "protocol_script": [
                    {"tool": {"name": "read", "args": {"path": "$WORKSPACE/input.json"}}},
                    {
                        "tool": {
                            "name": "write",
                            "args": {
                                "path": "$WORKSPACE/output.json",
                                "expectedSha256": None,
                                "content": '{"sum":' + str(total) + "}",
                            },
                        }
                    },
                    {"text": "Saved output.json."},
                ],
            }
        )
    return freeze_suite(
        "roami-rsi-protocol-smoke-v1",
        cases,
        purpose="Harness verification only. Scripted models do not measure agent capability.",
    )
