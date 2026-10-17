#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 2 ]]; then
  echo 'Usage: isolated-roami.sh <new-instance-directory> <command> [args...]' >&2
  exit 2
fi
INSTANCE_DIR="$1"
shift
mkdir -p "$INSTANCE_DIR"
INSTANCE_DIR="$(cd "$INSTANCE_DIR" && pwd -P)"
for prefix in ROAMI ROAM TTMUX; do
  for suffix in HOME DATA CONFIG DATABASE_DIR BACKUP_DIR; do
    unset "${prefix}_${suffix}"
  done
done
export ROAMI_HOME="$INSTANCE_DIR"
export ROAMI_DATA="$INSTANCE_DIR"
export ROAMI_CONFIG="$INSTANCE_DIR/config.yaml"
export ROAMI_DATABASE_DIR="$INSTANCE_DIR/database"
export ROAMI_BACKUP_DIR="$INSTANCE_DIR/backups"
exec "$@"
