#!/usr/bin/env bash
# Preserve retired entry points outside PATH and skill discovery roots.

retire_roami_path() {
    local path="$1" checksum archive
    [[ -e "$path" || -L "$path" ]] || return 0
    checksum="$(printf '%s' "$path" | cksum | awk '{print $1}')"
    archive="${ROAMI_CLI_RETIRE_DIR:-${ROAMI_BACKUP_DIR:-${ROAMI_HOME:-$HOME/.roami}/backups}/cli-entry-migration/$(date -u +%Y%m%dT%H%M%SZ)-$$}"
    (umask 077; mkdir -p "$archive")
    mv "$path" "$archive/${checksum}-$(basename "$path")"
}

retire_roami_session_entries() {
    local directory="$1" name
    for name in ttmux ttmux.bash-backup ttmux-poke; do
        retire_roami_path "$directory/$name"
    done
    retire_roami_path "$HOME/.bash_completion.d/ttmux"
}

retire_roami_session_skill() {
    retire_roami_path "$1/ttmux"
    retire_roami_path "$1/ttmux.md"
}
