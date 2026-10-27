#!/usr/bin/env bash
set -euo pipefail

scope="$(cd "$(dirname "${BASH_SOURCE[0]}")/../quality" && pwd)/python-check-scope.sh"
# Hooks export repository paths; the fixture must never inherit them.
while IFS= read -r name; do unset "$name"; done < <(git rev-parse --local-env-vars)
fixture="$(mktemp -d /tmp/roami-python-scope.XXXXXX)"
trap 'rm -rf "$fixture"' EXIT
cd "$fixture"
git init -q -b main
git config user.name 'Scope Test'
git config user.email 'scope-test@example.invalid'
git config core.hooksPath /dev/null
mkdir -p frontend agent-runtime/src cases/case-1-example
printf 'initial\n' > frontend/page.tsx
printf 'initial\n' > agent-runtime/src/agent.py
printf '{}\n' > agent-runtime/src/commands.json
printf 'lock\n' > agent-runtime/uv.lock
printf 'name: Example\ndescription: Runtime case\n' > cases/case-1-example/CASE.md
printf 'initial\n' > python-tool.py
git add .
git commit -qm initial
git update-ref refs/remotes/origin/main HEAD
base="$(git rev-parse HEAD)"

expect() {
  local expected="$1" mode="$2" label="$3" actual
  actual="$(env -u QUALITY_BASE_SHA -u QUALITY_HEAD_SHA bash "$scope" "$mode")"
  if [ "$actual" != "$expected" ]; then
    echo "$label: expected $expected, got $actual" >&2
    exit 1
  fi
}

expect false full 'clean tree'
printf 'docs\n' > README.md
git add README.md
expect false quick 'documentation only'
git reset -q HEAD README.md
rm README.md
printf 'frontend\n' >> frontend/page.tsx
git add frontend/page.tsx
expect false quick 'staged frontend'
printf 'python\n' >> agent-runtime/src/agent.py
expect false quick 'unstaged Python excluded from commit'
expect true full 'unstaged Python included in full check'
git restore agent-runtime/src/agent.py
git commit -qm frontend
expect false full 'committed frontend branch'
printf 'new\n' > new.py
expect true full 'untracked Python'
git add new.py
expect true quick 'added Python'
git reset -q HEAD new.py
rm new.py
git rm -q agent-runtime/src/agent.py
expect true quick 'deleted Python'
git reset -q HEAD
git restore .
git mv python-tool.py python-tool.txt
expect true quick 'renamed Python'
git reset -q HEAD
git restore .
rm python-tool.txt
printf 'resource\n' >> agent-runtime/src/commands.json
git add agent-runtime/src/commands.json
expect true quick 'runtime resource'
git reset -q HEAD
git restore .
printf 'metadata\n' >> cases/case-1-example/CASE.md
git add cases/case-1-example/CASE.md
expect true quick 'case metadata resource'
git reset -q HEAD
git restore .
git rm -q cases/case-1-example/CASE.md
expect true quick 'deleted case resource'
git reset -q HEAD
git restore .
printf 'dependency\n' >> agent-runtime/uv.lock
git add agent-runtime/uv.lock
expect true quick 'dependency lock'
git reset -q HEAD
git restore .
printf '[pytest]\n' > pytest.ini
git add pytest.ini
expect true quick 'root Python configuration'
git reset -q HEAD
rm pytest.ini
printf 'python\n' >> agent-runtime/src/agent.py
git add agent-runtime/src/agent.py
git commit -qm python
expect true full 'committed Python branch'
[[ "$(QUALITY_BASE_SHA="$base" QUALITY_HEAD_SHA=HEAD bash "$scope" full)" = true ]]
before_frontend="$(git rev-parse HEAD)"
printf 'frontend\n' >> frontend/page.tsx
git add frontend/page.tsx
git commit -qm frontend-only-push
[[ "$(QUALITY_BASE_SHA="$before_frontend" QUALITY_HEAD_SHA=HEAD bash "$scope" full)" = false ]]
[[ "$(QUALITY_BASE_SHA=missing-base bash "$scope" full 2>/dev/null)" = true ]]
echo 'Python check scope passed: staged, branch, CI range, additions, deletions, renames, resources, dependencies, and missing history'
