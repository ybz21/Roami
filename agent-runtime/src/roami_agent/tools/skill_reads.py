"""Identify visible reads of the current registered workflow instructions."""

import json

from roami_agent.protocol.skill_names import skill_location


def skill_request(call):
    function = call.get("function", {})
    if not isinstance(function, dict):
        return None
    if function.get("name") not in ("read", "skill_read"):
        return None
    try:
        args = json.loads(function.get("arguments", ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(args, dict):
        return None
    if function.get("name") == "read":
        path = args.get("path")
        if not isinstance(path, str) or not path.startswith("skill://"):
            return None
        name, _, reference = path.removeprefix("skill://").partition("/")
    elif function.get("name") == "skill_read":
        name, reference = args.get("name"), args.get("reference", "")
    else:
        return None
    if not isinstance(name, str) or not isinstance(reference, str):
        return None
    return skill_location(name, reference)


def loaded_workflows(messages, skills):
    calls, selected = {}, {}
    for message in messages:
        if message.get("role") == "assistant":
            pending = message.get("tool_calls")
            for call in pending if isinstance(pending, list) else []:
                if isinstance(call, dict) and isinstance(call.get("id"), str):
                    calls[call["id"]] = skill_request(call)
        if message.get("role") != "tool":
            continue
        call_id = message.get("tool_call_id")
        target = calls.get(call_id) if isinstance(call_id, str) else None
        if not target:
            continue
        name, reference = target
        skill = skills.get(name)
        if not skill:
            continue
        try:
            value = json.loads(message.get("content", ""))
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict) or "error" in value:
            continue
        observed = skill.get("references", {}).get(reference) if reference else skill
        if not observed or not skill.get("version"):
            continue
        if (
            value.get("version") != observed["version"]
            or value.get("text") != observed["text"]
            or reference
            and value.get("skillVersion") != skill["version"]
        ):
            continue
        location = "skill://" + name + ("/" + reference if reference else "")
        selected[location] = {
            "name": name,
            "location": location,
            "version": skill["version"],
            **({"referenceVersion": observed["version"]} if reference else {}),
        }
    return list(selected.values())
