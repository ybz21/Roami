"""Keep artifact reviews bound to the files and native state checked by the grader."""

import hashlib
import re

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.integrations.artifact_paths import relative_file
from roami_agent.protocol.errors import DomainError

CHANGED = "RSI_ARTIFACT_EVIDENCE_CHANGED"
SNAPSHOTS = {"company": "company-snapshot.json", "company_stock": "stock-snapshot.json"}


def artifact_workspace(case, root):
    return root / (
        "stock-remote" if case.get("judge", {}).get("kind") == "company_stock" else "workspace"
    )


def assert_review_sources(case, grade, root, artifacts=()):
    workspace = artifact_workspace(case, root)
    bindings = {}

    def bind(path, sha):
        require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha), CHANGED)
        require(path not in bindings or bindings[path] == sha, CHANGED)
        bindings[path] = sha

    try:
        evidence = grade.get("evidence", [])
        require(isinstance(evidence, list), CHANGED)
        for item in evidence:
            require(isinstance(item, dict), CHANGED)
            names = [item[key] for key in ("path", "remote_path") if key in item]
            if item.get("source") == "host_native_snapshot":
                require(not names, CHANGED)
                name = SNAPSHOTS.get(case.get("judge", {}).get("kind"))
                require(name is not None, CHANGED)
                bind(relative_file(root, name), item.get("sha256"))
            elif names:
                require(all(name == names[0] for name in names), CHANGED)
                bind(relative_file(workspace, names[0]), item.get("sha256"))
        for item in artifacts:
            bind(relative_file(workspace, item["file"]), item.get("sha256"))
        for path, sha in bindings.items():
            require(path.is_file() and not path.is_symlink(), CHANGED)
            require(hashlib.sha256(path.read_bytes()).hexdigest() == sha, CHANGED)
    except (DomainError, OSError, KeyError, TypeError, ValueError):
        raise DomainError(CHANGED) from None
