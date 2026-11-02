"""Run TASK-NEW01 conversation scenarios."""

import runpy
import sys
from pathlib import Path

sys.argv[1:1] = ["--case", "TASK-NEW01"]
runpy.run_path(
    str(
        Path(__file__).resolve().parents[3]
        / "scripts/dev/run-conversation-scenarios.py"
    ),
    run_name="__main__",
)
