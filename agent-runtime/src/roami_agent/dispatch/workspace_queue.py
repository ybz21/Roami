"""Directory admission for already resolved task targets, independent of workspace IDs."""

import json
import os


def directory_key(task):
    try:
        target = json.loads(task.get("target_json") or "null")
        intent = json.loads(task.get("intent_json") or "{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(target, dict):
        target = intent.get("target", {}) if isinstance(intent, dict) else {}
    if not isinstance(target, dict):
        return None
    workspace = target.get("workspace")
    directory = (
        (workspace.get("directory") if isinstance(workspace, dict) else None)
        or target.get("workdir")
        or target.get("directory")
    )
    node = target.get("nodeId", "local")
    if not isinstance(directory, str) or not os.path.isabs(directory) or not isinstance(node, str):
        return None
    return node, os.path.realpath(directory) if node == "local" else os.path.normpath(directory)


def occupied_directories(running, active):
    current = {task["id"]: directory_key(task) for task in running}
    occupied = {key for key in current.values() if key is not None}
    preparing = False
    for item in active.values():
        if item.get("kind") != "task.run":
            continue
        key = current.get(item.get("task")) or item.get("directory")
        if key is None:
            preparing = True
        else:
            occupied.add(key)
    return occupied, preparing
