# Host verification tests

These tests inspect the repository build, invoke its download scripts, or exercise the trusted RSI evaluator and its reference admission. Run them from the complete checkout with the normal `pytest`/quality gates. They remain required in host checks and CI.

The frozen Actor regression gate excludes this directory and the existing `test_improvement*.py` evaluator tests. It mounts runtime tests only; it does not supply repository scripts, the Case catalog, references, or a Docker daemon to the Actor. Runtime failures still reject promotion. `test_candidate_regression_boundary.py` executes real containers to check both exclusions and failure propagation.

Runtime host-command tests (`test_host_execution.py`, `test_host_processes.py`) stay in the Actor pack. A host command implemented by the Agent is runtime behavior, not an evaluator dependency.
