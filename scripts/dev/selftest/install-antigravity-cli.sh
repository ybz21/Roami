#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
fixture="$(mktemp -d /tmp/roami-install-antigravity.XXXXXX)"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/tools" "$fixture/slot/install"
sed '/^# ── 主流程/,$d' "$repo/install.sh" > "$fixture/installer-functions.sh"
cp "$repo/internal/agentinventory/install-antigravity-cli.sh" "$fixture/slot/install/"
for program in bash cat chmod env grep id mkdir mktemp rm; do
  ln -s "$(command -v "$program")" "$fixture/tools/$program"
done

cat > "$fixture/tools/curl" <<'CURL'
#!/bin/bash
set -euo pipefail
[[ "${@: -3:1}" = https://antigravity.google/cli/install.sh && "${@: -2:1}" = -o ]]
printf 'download\n' >> "$TEST_INSTALL_LOG"
cat > "${@: -1}" <<'BOOTSTRAP'
#!/bin/bash
set -euo pipefail
[[ "$#" = 2 && "$1" = --dir ]]
mkdir -p "$2"
cat > "$2/agy" <<'AGY'
#!/bin/bash
case "$1" in
  --version) echo 1.5.15 ;;
  --help)
    printf 'Usage of agy:\n  %s argument\n' --conversation --prompt-interactive --print --input-format --output-format --settings --disable-slash-commands
    exit 1
    ;;
  *) exit 1 ;;
esac
AGY
chmod +x "$2/agy"
BOOTSTRAP
CURL
chmod +x "$fixture/tools/curl"

(
  export PATH="$fixture/tools" TEST_INSTALL_LOG="$fixture/install.log" ROAMI_SYSTEM=0
  source "$fixture/installer-functions.sh"
  INSTALL_RUN_HOME="$fixture/service user"
  INSTALL_SLOT="$fixture/slot"

  ROAMI_INSTALL_ANTIGRAVITY=0 install_antigravity
  test ! -e "$TEST_INSTALL_LOG" && test -z "$INSTALL_ANTIGRAVITY_PATH"
  ROAMI_INSTALL_ANTIGRAVITY=1 install_antigravity
  ROAMI_INSTALL_ANTIGRAVITY=1 install_antigravity
  [[ "$(cat "$TEST_INSTALL_LOG")" = download ]]
  grep -Fx "Environment=\"PATH=$INSTALL_RUN_HOME/.local/bin:$PATH\"" <(service_path_environment)
  grep -F "<key>PATH</key><string>$INSTALL_RUN_HOME/.local/bin:$PATH</string>" <(service_path_environment plist)

  printf '#!/bin/bash\nprintf "1.5.15\\n"\n' > "$INSTALL_RUN_HOME/.local/bin/agy"
  if (ROAMI_INSTALL_ANTIGRAVITY=1 install_antigravity) > "$fixture/incompatible.log" 2>&1; then
    echo 'Deployment accepted an incompatible agy binary' >&2
    exit 1
  fi
  grep -q -- '--conversation' "$fixture/incompatible.log"
  [[ "$(cat "$TEST_INSTALL_LOG")" = download ]]
)
echo 'PASS: Antigravity bootstrap, validation, reuse and service PATH'
