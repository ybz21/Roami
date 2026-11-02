"""Public run overview assembled from repository rows."""

from roami_agent.improvement.integrations.spending_policy import uses_shared_model_limit
from roami_agent.protocol.errors import DomainError


def run_overview(records, owner):
    runs, issues = records.list_overview(owner)
    from roami_agent.improvement.integrations.github_client import publication_profile

    try:
        publication = publication_profile(records.ledger.path.parent, owner)
    except (DomainError, OSError, ValueError):
        publication = None
    return {
        "settings": {
            key: val
            for key, val in records.settings(owner).items()
            if not uses_shared_model_limit(records.ledger) or key in {"revision", "auto_publish"}
        },
        "runs": runs,
        "issues": issues,
        "publication": {"repository": publication["repository"] if publication else None},
    }
