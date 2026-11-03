#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -z "${ROAMI_SESSION_E2E_ROOT:-}" ]]; then
  test_root="$(mktemp -d /tmp/roami-session-e2e.XXXXXX)"
  trap '"$REPO/scripts/dev/isolated-roami.sh" "$test_root" --stop' EXIT
  "$REPO/scripts/dev/isolated-roami.sh" "$test_root" env ROAMI_SESSION_E2E_ROOT="$test_root" bash "$0"
  exit $?
fi

binary="$ROAMI_SESSION_E2E_ROOT/roami"
(cd "$REPO" && go build -o "$binary" ./cmd/roami)
CLI=("$binary" session)
jget() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
check() { [[ "$2" == "$3" ]] || { echo "FAIL: $1 expected=$2 actual=$3"; exit 1; }; echo "PASS: $1"; }

"${CLI[@]}" help | rg -q 'Roami Main'
"$binary" help | rg -q 'swarm <命令>'
"$binary" swarm help | rg -q -- '--task-revision'
"$binary" swarm stop --help | rg -q '只停新派发'
sid="$("${CLI[@]}" new 'session-e2e' --detach --no-reuse --json | jget 'd["session"]')"
check 'stable session ID' "$sid" "$("${CLI[@]}" resolve session-e2e --strict --json | jget 'd["name"]')"
"${CLI[@]}" send "$sid" "printf 'SESSION_E2E_OK\\n'" >/dev/null
for attempt in $(seq 1 20); do
  output="$("${CLI[@]}" capture "$sid" --lines 30)"
  if [[ "$output" == *SESSION_E2E_OK* ]]; then break; fi
  sleep 0.1
done
[[ "$output" == *SESSION_E2E_OK* ]]
echo 'PASS: prompt submission and capture'
"${CLI[@]}" rename "$sid" 'session-e2e-renamed' >/dev/null
check 'rename preserves ID' "$sid" "$("${CLI[@]}" resolve session-e2e-renamed --strict --json | jget 'd["name"]')"
before="$("${CLI[@]}" ls --json | jget 'len(d)')"
for command in add adopt activate done task sql watch listen; do
  if "${CLI[@]}" swarm "$command" obsolete >/dev/null 2>&1; then
    echo "FAIL: removed swarm command accepted: $command"; exit 1
  fi
done
if "$binary" swarm new group --goal build >/dev/null 2>&1; then
  echo 'FAIL: creation accepted without idempotency key'; exit 1
fi
check 'rejected commands preserve sessions' "$before" "$("${CLI[@]}" ls --json | jget 'len(d)')"
"${CLI[@]}" kill "$sid" --yes >/dev/null
echo 'PASS: session CLI and managed swarm boundary'
