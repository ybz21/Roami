#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROAMI_TEST_BIN="${ROAMI_BIN:-$(command -v roami)}"
INSTANCE="$(mktemp -d /tmp/roami-session-cli.XXXXXX)"
cleanup() {
    bash "$REPO_DIR/scripts/dev/isolated-roami.sh" "$INSTANCE" --stop
    rm -rf "$INSTANCE"
}
trap cleanup EXIT
session_cli() {
    TTMUX_FORCE_PROMPT_SUBMIT=0 bash "$REPO_DIR/scripts/dev/isolated-roami.sh" "$INSTANCE" "$ROAMI_TEST_BIN" session "$@"
}
read_session_id() { python3 -c 'import json,sys;print(json.load(sys.stdin)["session"])'; }
ln -s "$ROAMI_TEST_BIN" "$INSTANCE/ttmux"
if bash "$REPO_DIR/scripts/dev/isolated-roami.sh" "$INSTANCE" "$INSTANCE/ttmux" server --help > "$INSTANCE/retired.txt" 2>&1; then
    echo 'Retired executable still accepted server mode' >&2
    exit 1
fi
grep -q 'entry retired' "$INSTANCE/retired.txt"
session_cli help > "$INSTANCE/help.txt"
[[ "$(session_cli --version)" == 'roami session v'* ]]
parent="$(session_cli new cli-parent --dir "$INSTANCE" --detach --json | read_session_id)"
child="$(session_cli fork "$parent" cli-child --dir "$INSTANCE" --detach --json | read_session_id)"
session_cli rename "$child" renamed-child > /dev/null
session_cli resolve "$child" --strict --json > "$INSTANCE/resolved.json"
python3 - "$INSTANCE/resolved.json" <<'PY'
import json,sys
assert json.load(open(sys.argv[1]))['label']=='renamed-child'
PY
if session_cli keys "$child" -t > "$INSTANCE/bad-key.txt" 2>&1; then
    echo 'Raw tmux option accepted as key' >&2
    exit 1
fi
session_cli send "$child" "printf 'ROAMI_CLI_RESTORED\\n'" > /dev/null
for attempt in 1 2 3 4 5; do
    session_cli capture "$child" > "$INSTANCE/capture.txt"
    if grep -qx ROAMI_CLI_RESTORED "$INSTANCE/capture.txt"; then break; fi
    sleep 1
done
grep -qx ROAMI_CLI_RESTORED "$INSTANCE/capture.txt"
for command in kill-server killall list-sessions; do
    if session_cli "$command" > "$INSTANCE/rejected.txt" 2>&1; then
        echo "Unexpectedly accepted $command" >&2
        exit 1
    fi
    session_cli resolve "$parent" --strict --json > /dev/null
done
shadow="$(session_cli new renamed-child --no-reuse --dir "$INSTANCE" --detach --json | read_session_id)"
if session_cli kill renamed-child --yes > "$INSTANCE/ambiguous.txt" 2>&1; then
    echo 'Ambiguous label was accepted for close' >&2
    exit 1
fi
session_cli resolve "$child" --strict --json > /dev/null
session_cli resolve "$shadow" --strict --json > /dev/null
session_cli kill "$shadow" --yes > /dev/null
session_cli kill "$child" --yes > /dev/null
session_cli resolve "$parent" --strict --json > /dev/null
session_cli kill "$parent" --yes > /dev/null
printf 'PASS: create, fork, rename, resolve, submit, capture, targeted close; global and native commands rejected\n'
