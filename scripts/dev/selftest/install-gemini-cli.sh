#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
fixture="$(mktemp -d /tmp/roami-install-gemini.XXXXXX)"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/tools" "$fixture/slot/install"
sed '/^# ── 主流程/,$d' "$repo/install.sh" > "$fixture/installer-functions.sh"
cp "$repo/scripts/deploy/install-gemini-cli.sh" "$fixture/slot/install/"
for program in bash cat chmod env grep id mkdir; do
  ln -s "$(command -v "$program")" "$fixture/tools/$program"
done

cat > "$fixture/tools/node" <<'NODE'
#!/bin/bash
exit "${TEST_NODE_STATUS:-0}"
NODE
cat > "$fixture/tools/npm" <<'NPM'
#!/bin/bash
set -euo pipefail
[[ "$#" = 5 && "$1" = install && "$2" = --global && "$3" = --prefix && "$5" = @google/gemini-cli ]]
printf '%s\n' "$5" >> "$TEST_NPM_LOG"
mkdir -p "$4/bin"
cat > "$4/bin/gemini" <<'GEMINI'
#!/bin/bash
case "$1" in
  --version) echo 0.70.0 ;;
  --help) echo '--session-id --resume --prompt-interactive --output-format' ;;
  *) exit 1 ;;
esac
GEMINI
chmod +x "$4/bin/gemini"
NPM
chmod +x "$fixture/tools/"{node,npm}

(
  export PATH="$fixture/tools" TEST_NPM_LOG="$fixture/npm.log" ROAMI_SYSTEM=0
  source "$fixture/installer-functions.sh"
  INSTALL_RUN_HOME="$fixture/service user"
  INSTALL_SLOT="$fixture/slot"

  ROAMI_INSTALL_GEMINI=0 install_gemini
  test ! -e "$TEST_NPM_LOG" && test -z "$INSTALL_GEMINI_PATH"

  if (export TEST_NODE_STATUS=1; ROAMI_INSTALL_GEMINI=1 install_gemini) > "$fixture/old-node.log" 2>&1; then
    echo 'Gemini installation accepted an incompatible Node.js' >&2
    exit 1
  fi
  grep -q 'Node.js 20+' "$fixture/old-node.log"
  test ! -e "$TEST_NPM_LOG"

  ROAMI_INSTALL_GEMINI=1 install_gemini
  ROAMI_INSTALL_GEMINI=1 install_gemini
  [[ "$(cat "$TEST_NPM_LOG")" = @google/gemini-cli ]]
  grep -Fx "Environment=\"PATH=$INSTALL_RUN_HOME/.local/bin:$PATH\"" <(service_path_environment)
  grep -F "<key>PATH</key><string>$INSTALL_RUN_HOME/.local/bin:$PATH</string>" <(service_path_environment plist)

  printf '#!/bin/bash\necho unrelated-gemini\n' > "$INSTALL_RUN_HOME/.local/bin/gemini"
  if (ROAMI_INSTALL_GEMINI=1 install_gemini) > "$fixture/incompatible.log" 2>&1; then
    echo 'Deployment accepted an incompatible Gemini binary' >&2
    exit 1
  fi
  grep -q -- '--session-id' "$fixture/incompatible.log"
  [[ "$(cat "$TEST_NPM_LOG")" = @google/gemini-cli ]]
)
echo 'PASS: Gemini opt-in deployment, npm prefix, verification, reuse and service PATH'
