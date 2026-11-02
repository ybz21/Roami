"""Private artifact creation and workspace materialization."""

import base64
import json
import os

from roami_agent.improvement.integrations.artifact_paths import relative_file


def private_json(path, value):
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def materialize(case, workspace):
    workspace.mkdir(mode=0o700)
    for name, content in case.get("files", {}).items():
        path = relative_file(workspace, name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(content)
    for name, content in case.get("asset_files", {}).items():
        path = relative_file(workspace, name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = base64.b64decode(content, validate=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
