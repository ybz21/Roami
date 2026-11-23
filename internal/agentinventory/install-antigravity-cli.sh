#!/usr/bin/env bash
set -euo pipefail

bin_dir="${1:?Usage: install-antigravity-cli.sh BIN_DIR}"
export PATH="$bin_dir:$PATH"

if ! command -v agy >/dev/null; then
  installer="$(mktemp)"
  trap 'rm -f "$installer"' EXIT
  curl -fsSL --retry 2 --connect-timeout 10 --max-time 60 \
    https://antigravity.google/cli/install.sh -o "$installer"
  bash "$installer" --dir "$bin_dir"
fi

version="$(agy --version)"
status=0
help="$(agy --help 2>&1)" || status=$?
# Some agy releases print their help and exit with status 1.
[ "$status" -le 1 ] || exit "$status"
for flag in --conversation --prompt-interactive --print --input-format --output-format --settings --disable-slash-commands; do
  if ! grep -Eq -- "^[[:space:]]*$flag([[:space:]]|$)" <<< "$help"; then
    printf '当前 agy 缺少 %s，请升级官方 Antigravity CLI。\n' "$flag" >&2
    exit 1
  fi
done
printf 'Antigravity CLI %s (%s)\n' "$version" "$(command -v agy)"
