"""Select complete cold rounds; active and unhanded-off sources stay in the prompt."""

import hashlib

from roami_agent.protocol.serialization import encoded

POLICY_VERSION = "home-retention-v1"


def source_fingerprint(messages):
    return hashlib.sha256(
        encoded(
            [
                [
                    m["id"],
                    m["branch_id"],
                    m["turn_id"],
                    m["seq"],
                    m["created_ms"],
                    m["role"],
                    m["status"],
                    m["content_json"],
                    bool(m.get("agent_task_instruction")),
                ]
                for m in messages
            ]
        ).encode()
    ).hexdigest()


def complete_groups(messages, completed):
    groups = []
    for index, message in enumerate(messages):
        tid = message["turn_id"]
        if not tid or tid not in completed:
            break
        if not groups or groups[-1][0] != tid:
            groups.append([tid, index, index + 1, message["created_ms"]])
        else:
            groups[-1][2] = index + 1
    return groups


def cold_cut(messages, completed, timestamp, *, hours=48, turns=20):
    groups = complete_groups(messages, completed)
    cutoff = timestamp - hours * 3_600_000
    cut = 0
    for index, (_, _, end, created) in enumerate(groups):
        if created < cutoff or index < len(groups) - turns:
            cut = end
    return cut


def batch_end(messages, completed, covered, *, characters=32_000, turns=20):
    end, size, count = covered, 0, 0
    for _, start, stop, _ in complete_groups(messages, completed):
        if stop <= covered:
            continue
        added = sum(
            (
                len(m["content_json"])
                if m["role"] == "user" and not m.get("agent_task_instruction")
                else min(len(m["content_json"]), 4000)
            )
            + 200
            for m in messages[start:stop]
        )
        if size + added > characters or count >= turns:
            break
        size += added
        count += 1
        end = stop
    return end
