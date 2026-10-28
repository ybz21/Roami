"""Hash the runtime implementation independently of evaluation layout."""

import hashlib
from functools import lru_cache
from pathlib import Path

from roami_agent.improvement.domain.contracts import digest


@lru_cache(maxsize=1)
def implementation_hash():
    root = Path(__file__).parents[2]
    return digest(
        {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py"))
        }
    )
