#!/usr/bin/env bash
set -euo pipefail

prefix="${1:?Usage: install-gemini-cli.sh NPM_PREFIX}"
export PATH="$prefix/bin:$PATH"

if ! command -v gemini >/dev/null 2>&1; then
  if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
    echo '安装 Gemini CLI 需要 Node.js 20+ 和 npm。' >&2
    exit 1
  fi
  if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)'; then
    echo '安装 Gemini CLI 需要 Node.js 20+。' >&2
    exit 1
  fi
  npm install --global --prefix "$prefix" @google/gemini-cli
fi

version="$(gemini --version)" || exit 1
help="$(gemini --help)" || exit 1
for flag in --session-id --resume --prompt-interactive --output-format; do
  if [[ "$help" != *"$flag"* ]]; then
    printf '当前 gemini 缺少 %s，请升级官方 Gemini CLI。\n' "$flag" >&2
    exit 1
  fi
done
printf 'Gemini CLI %s (%s)\n' "$version" "$(command -v gemini)"
