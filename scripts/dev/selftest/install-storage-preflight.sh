#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SANDBOX="$(mktemp -d /tmp/roami-install-preflight.XXXXXX)"
trap 'rm -rf "$SANDBOX"' EXIT
export ROAMI_BIN_DIR="$SANDBOX/bin"
export ROAMI_SYSTEM=0
mkdir -p "$ROAMI_BIN_DIR"
sed '/^# ── 主流程/,$d' "$REPO_DIR/install.sh" > "$SANDBOX/installer-functions.sh"
printf 'existing-install\n' > "$ROAMI_BIN_DIR/roami"
cat > "$ROAMI_BIN_DIR/roami.tmp" <<'CANDIDATE'
#!/bin/sh
printf '{"migrationRequired":true,"mode":"uninitialized"}\n'
CANDIDATE
if bash -c 'source "$1"; preflight_storage "$2"' _ "$SANDBOX/installer-functions.sh" "$ROAMI_BIN_DIR/roami.tmp" > "$SANDBOX/blocked.log" 2>&1; then
  echo 'preflight accepted a legacy database layout' >&2
  exit 1
fi
[[ "$(cat "$ROAMI_BIN_DIR/roami")" = existing-install ]]
[[ -x "$ROAMI_BIN_DIR/roami.upgrade" ]]
cat > "$ROAMI_BIN_DIR/roami.tmp" <<'CANDIDATE'
#!/bin/sh
printf '{"migrationRequired":false,"mode":"uninitialized"}\n'
CANDIDATE
bash -c 'source "$1"; preflight_storage "$2"' _ "$SANDBOX/installer-functions.sh" "$ROAMI_BIN_DIR/roami.tmp"
[[ "$(cat "$ROAMI_BIN_DIR/roami")" = existing-install ]]
cat > "$ROAMI_BIN_DIR/roami.tmp" <<'CANDIDATE'
#!/bin/sh
exit 42
CANDIDATE
if bash -c 'source "$1"; preflight_storage "$2"' _ "$SANDBOX/installer-functions.sh" "$ROAMI_BIN_DIR/roami.tmp" > "$SANDBOX/failed.log" 2>&1; then
  echo 'preflight accepted a failed storage inspection' >&2
  exit 1
fi
[[ "$(cat "$ROAMI_BIN_DIR/roami")" = existing-install ]]
echo 'Install storage preflight passed: legacy/error preserve current installation; fresh layout accepted'

export ROAMI_DATABASE_DIR="$SANDBOX/a & b<database>"
bash -c 'source "$1"; service_path_environment plist' _ "$SANDBOX/installer-functions.sh" > "$SANDBOX/environment.xml"
python3 - "$SANDBOX/environment.xml" "$ROAMI_DATABASE_DIR" <<'PYXML'
import sys,xml.etree.ElementTree as ET
root = ET.fromstring('<dict>' + open(sys.argv[1]).read() + '</dict>')
entries = list(root)
values = {entries[i].text: entries[i+1].text for i in range(0,len(entries),2)}
assert values['ROAMI_DATABASE_DIR'] == sys.argv[2], values
PYXML
echo 'LaunchAgent storage environment preserves explicit paths and XML characters'
