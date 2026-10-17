#!/usr/bin/env bash
set -euo pipefail
OUT="${1:-${HOME}/.local/bin/chrome}"
mkdir -p "$(dirname "$OUT")"
cat > "$OUT" <<'LAUNCHER'
#!/bin/sh
exec roami chrome "$@"
LAUNCHER
chmod +x "$OUT"
bash -n "$OUT"
