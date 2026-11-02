"""Run the frozen MECH-SI01 task recovery selection."""

import runpy
import sys
from pathlib import Path

sys.argv[1:1] = ["--case", "MECH-SI01"]
runpy.run_path(
    str(Path(__file__).resolve().parents[3] / "scripts/dev/run-task-recovery-cases.py"),
    run_name="__main__",
)
