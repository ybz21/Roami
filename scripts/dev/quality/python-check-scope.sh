#!/usr/bin/env bash
set -euo pipefail
mode=full
if [ "$#" -gt 0 ]; then mode="$1"; fi
node "$(dirname "$0")/python-check-plan.mjs" "$mode" --runtime
