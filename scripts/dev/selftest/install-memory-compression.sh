#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SANDBOX="$(mktemp -d /tmp/roami-install-memory.XXXXXX)"
trap 'rm -rf "$SANDBOX"' EXIT
sed '/^# ── 主流程/,$d' "$REPO_DIR/install.sh" > "$SANDBOX/installer-functions.sh"
export ROAMI_SYSTEM=0
source "$SANDBOX/installer-functions.sh"
INSTALL_SLOT="$SANDBOX/release slot"
INSTALL_ROOT="$SANDBOX/installation root"
INSTALL_WORK="$SANDBOX/work"
mkdir -p "$INSTALL_SLOT/bin" "$INSTALL_WORK"
export MEMORY_TEST_STATE="$SANDBOX/status" MEMORY_TEST_SETUP="$REPO_DIR/internal/memguard/zram-setup.sh"
cat > "$INSTALL_SLOT/bin/roami" <<'CLI'
#!/usr/bin/env bash
case "$1 $2" in
  'session memory-status') cat "$MEMORY_TEST_STATE" ;;
  'session memory-setup-script') cat "$MEMORY_TEST_SETUP" ;;
  *) exit 2 ;;
esac
CLI
chmod +x "$INSTALL_SLOT/bin/roami"

memory_compression_supported() { [ "$supported" = yes ]; }
id() { [ "$1" = -u ] && printf '%s\n' "$uid"; }
sudo() {
  printf '%s\n' "$*" >> "$SANDBOX/sudo-calls"
  [ "$sudo_allowed" = yes ] || return 1
  [ "$1" != -n ] || shift
  "$@"
}
bash() {
  if [ "${!#}" = --dry-run ]; then command bash "$@"; return; fi
  printf '%s\n' "$*" >> "$SANDBOX/setup-calls"
  [ "$setup_succeeds" = yes ] || return 1
  [ "$activate" != yes ] || printf '{"zram":true,"zswap":false}\n' > "$MEMORY_TEST_STATE"
}
reset_case() {
  OS=linux; supported=yes; uid=0; sudo_allowed=yes; setup_succeeds=yes; activate=yes
  unset ROAMI_NO_ZRAM ROAMI_ZRAM_SIZE ROAMI_ZRAM_MEMORY_LIMIT
  printf '{"zram":false,"zswap":false}\n' > "$MEMORY_TEST_STATE"
  rm -f "$SANDBOX/setup-calls" "$SANDBOX/sudo-calls"
}
run_case() { ensure_memory_compression > "$SANDBOX/$1.log" 2>&1; }
no_setup() { [ ! -e "$SANDBOX/setup-calls" ] && [ ! -e "$SANDBOX/sudo-calls" ]; }

reset_case
OS=darwin; run_case macos; no_setup
reset_case
supported=no; run_case no-systemd; no_setup
reset_case
ROAMI_NO_ZRAM=1; run_case opt-out; no_setup
for backend in zram zswap; do
  reset_case
  if [ "$backend" = zram ]; then printf '{"zram":true,"zswap":false}\n' > "$MEMORY_TEST_STATE"
  else printf '{"zram":false,"zswap":true}\n' > "$MEMORY_TEST_STATE"; fi
  run_case "existing-$backend"; no_setup
  grep -q '保留现有配置' "$SANDBOX/existing-$backend.log"
done
reset_case
printf 'old version without memory-status\n' > "$MEMORY_TEST_STATE"
run_case old-version; no_setup
reset_case
ROAMI_ZRAM_SIZE='16G; invalid'; run_case invalid-size; no_setup
reset_case
ROAMI_ZRAM_MEMORY_LIMIT='-1G'; run_case invalid-limit; no_setup
reset_case
uid=1000; sudo_allowed=no; run_case no-permission
[ ! -e "$SANDBOX/setup-calls" ]
grep -q '^-n bash ' "$SANDBOX/sudo-calls"
grep -q '稍后执行' "$SANDBOX/no-permission.log"
cmp "$MEMORY_TEST_SETUP" "$INSTALL_ROOT/system/roami-zram-setup.sh"
reset_case
setup_succeeds=no; run_case setup-failure
grep -q '未能启用' "$SANDBOX/setup-failure.log"
reset_case
activate=no; run_case unconfirmed
grep -q '未能启用' "$SANDBOX/unconfirmed.log"
reset_case
run_case root-install
[ ! -e "$SANDBOX/sudo-calls" ]
grep -q '压缩交换区已启用' "$SANDBOX/root-install.log"
reset_case
uid=1000; ROAMI_ZRAM_SIZE=16G; ROAMI_ZRAM_MEMORY_LIMIT=4G
run_case first-install
grep -q '16G --memory-limit 4G$' "$SANDBOX/setup-calls"
grep -q '压缩交换区已启用' "$SANDBOX/first-install.log"
run_case repeat-install
[[ "$(wc -l < "$SANDBOX/setup-calls")" -eq 1 ]]

echo 'PASS: macOS/systemd/opt-out skips, existing zram/zswap, old releases, invalid sizes, unavailable sudo, setup failure, readback and idempotent deployment'
