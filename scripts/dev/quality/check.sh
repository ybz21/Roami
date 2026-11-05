#!/usr/bin/env bash
# Unified repository quality gate for local hooks and CI.
#
# Usage:
#   scripts/dev/quality/check.sh quick   # pre-commit friendly
#   scripts/dev/quality/check.sh full    # complete affected checks
#   scripts/dev/quality/check.sh release # all checks, regardless of changed paths
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
MODE="${1:-full}"

cd "$ROOT"

section() {
  printf '\n==> %s\n' "$1"
}

changed_files() {
  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    git -c core.quotePath=false diff --name-only --cached --diff-filter=ACMR
  else
    git -c core.quotePath=false diff --name-only --cached --diff-filter=ACMR
  fi
}

tracked_source_files() {
  git ls-files -z \
    '*.go' '*.py' '*.sh' '*.bash' '*.ts' '*.tsx' '*.js' '*.jsx' '*.mjs' '*.cjs' \
    ':!:frontend/dist/*' ':!:frontend/node_modules/*' |
    while IFS= read -r -d '' file; do
      [ ! -f "$file" ] || printf '%s\0' "$file"
    done
}

section "CLI entry audit"
node scripts/dev/quality/cli-entry-audit.mjs
bash scripts/dev/selftest/install-storage-preflight.sh
bash scripts/dev/selftest/install-release-discovery.sh
bash scripts/dev/selftest/retired-session-entries.sh
bash scripts/dev/selftest/python-check-scope.sh
node --test scripts/dev/selftest/python-check-plan.test.mjs

section "Shell syntax"
shell_files="$(git ls-files '*.sh' 'scripts/*.sh')"
if [ -n "$shell_files" ]; then
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    bash -n "$f"
  done <<< "$shell_files"
fi

section "Go formatting"
go_files="$(git ls-files '*.go')"
if [ -n "$go_files" ]; then
  unformatted="$(gofmt -l $(printf '%s\n' "$go_files" | while IFS= read -r f; do [ ! -f "$f" ] || printf '%s\n' "$f"; done))"
  if [ -n "$unformatted" ]; then
    printf 'Go files need gofmt:\n%s\n' "$unformatted" >&2
    exit 1
  fi
fi

python_plan="$(node scripts/dev/quality/python-check-plan.mjs "$MODE" --lines)"
python_enabled() {
  [[ $'\n'"$python_plan"$'\n' == *$'\n'"$1=true"$'\n'* ]]
}
section "Python check plan"
printf '%s\n' "$python_plan"
if python_enabled python && ! command -v uv >/dev/null 2>&1; then
  echo "uv is missing. Install uv, then run: cd agent-runtime && uv sync --frozen" >&2
  exit 1
fi
for profile in presentation tabular market video; do
  if python_enabled "$profile"; then
    bash scripts/dev/quality/python-skill-dependencies.sh "$profile"
  fi
done
if python_enabled go; then
  section "Go tests"
  go test ./...
else
  section "Go tests skipped (no related changes)"
fi
if python_enabled runtime; then
  section "Python Agent runtime"
  (cd agent-runtime && uv sync --frozen --quiet && uv run --frozen ruff check src tests && uv run --frozen ruff format --check src tests && uv run --frozen pytest -q)
else
  section "Python Agent runtime skipped (no related changes)"
fi

for profile in presentation tabular market video; do
  if python_enabled "$profile"; then
    section "Python Skill: $profile"
    bash scripts/dev/quality/python-skill-check.sh "$profile"
  fi
done

section "Frontend checks"
if [ ! -d frontend/node_modules ]; then
  echo "frontend/node_modules is missing. Run: cd frontend && npm install" >&2
  exit 1
fi
(cd frontend && npm run i18n:check)
(cd frontend && npm run hover:check)
(cd frontend && npm run typecheck)

if [ "$MODE" != quick ]; then
  section "Frontend build"
  (cd frontend && npm run build)
fi

section "Secret scan"
mapfile -d '' -t scan_files < <(tracked_source_files)
if [ "${#scan_files[@]}" -gt 0 ]; then
  if grep -nEI '(api[_-]?key|secret|token|password|passwd|private[_-]?key)[[:space:]]*[:=][[:space:]]*["'\''][^"'\'']{12,}' "${scan_files[@]}"; then
    echo "Potential hard-coded secret found. Move secrets to .env or documented configuration." >&2
    exit 1
  else
    scan_status=$?
    if [ "$scan_status" -ne 1 ]; then
      echo "Secret scan failed to read source files." >&2
      exit "$scan_status"
    fi
  fi
fi

section "Staged file policy"
staged="$(changed_files || true)"
if [ -n "$staged" ]; then
  if printf '%s\n' "$staged" | grep -Eq '(^|/)(node_modules|dist|coverage)/'; then
    echo "Generated dependency/build output is staged. Remove node_modules, dist, or coverage files from the commit." >&2
    exit 1
  fi
  if printf '%s\n' "$staged" | grep -Eq '(^|/)\.env$'; then
    echo ".env must not be committed. Use configs/config.yaml.template for documented config instead." >&2
    exit 1
  fi
  # 按内容拦编译产物：上面两条按名字认，而名字永远认不出下一个意外——
  # 一个 34MB 的后端二进制曾经落在 .gitignore 没盖住的路径上，就这么进了一次提交。
  # 仓库里最大的正经文件也就几百 KB，1MB 以上的二进制一律当误提交。
  while IFS= read -r f; do
    [ -n "$f" ] && [ -f "$f" ] || continue
    size="$(wc -c < "$f" | tr -d ' ')"
    [ "$size" -gt 1048576 ] || continue
    grep -Iq . "$f" 2>/dev/null && continue   # -I：二进制文件永不匹配
    echo "$f is a $((size / 1024 / 1024))MB binary. Build output must not be committed — add it to .gitignore." >&2
    exit 1
  done <<EOF
$staged
EOF
fi

section "Quality gate passed"
