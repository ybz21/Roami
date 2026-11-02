#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-full}"
paths="$(mktemp)"
trap 'rm -f "$paths"' EXIT

if [ -n "${QUALITY_BASE_SHA:-}" ]; then
  # Missing history must not silently skip a required check.
  if ! git diff --name-only --no-renames -z "$QUALITY_BASE_SHA" "${QUALITY_HEAD_SHA:-HEAD}" > "$paths"; then
    echo true
    exit 0
  fi
else
  git diff --cached --name-only --no-renames -z > "$paths"
  if [ "$MODE" != quick ] || [ ! -s "$paths" ]; then
    base="$(git merge-base HEAD refs/remotes/origin/main 2>/dev/null || git merge-base HEAD refs/heads/main 2>/dev/null || git rev-parse --verify HEAD^ 2>/dev/null || true)"
    if [ -z "$base" ]; then
      echo true
      exit 0
    fi
    git diff --name-only --no-renames -z "$base" HEAD > "$paths"
    git diff --name-only --no-renames -z HEAD >> "$paths"
    git ls-files --others --exclude-standard -z >> "$paths"
  fi
fi

while IFS= read -r -d '' path; do
  case "$path" in
    cases/*|agent-runtime/src/*|agent-runtime/tests/*|agent-runtime/agent.example.toml|*.py|pyproject.toml|*/pyproject.toml|uv.lock|*/uv.lock|pytest.ini|*/pytest.ini|tox.ini|*/tox.ini|ruff.toml|*/ruff.toml|.ruff.toml|*/.ruff.toml|.python-version|*/.python-version|requirements*.txt|*/requirements*.txt)
      echo true
      exit 0
      ;;
  esac
done < "$paths"
echo false
