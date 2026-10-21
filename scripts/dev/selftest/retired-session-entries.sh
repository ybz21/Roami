#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FIXTURE="$(mktemp -d /tmp/roami-entry-migration.XXXXXX)"
trap 'rm -rf "$FIXTURE"' EXIT
export HOME="$FIXTURE/home"
export ROAMI_CLI_RETIRE_DIR="$FIXTURE/archive"
mkdir -p "$HOME/.local/bin" "$HOME/.claude/skills/ttmux" "$HOME/.bash_completion.d" "$HOME/.codex/skills"
printf 'legacy skill\n' > "$HOME/.claude/skills/ttmux/SKILL.md"
printf 'old shell implementation\n' > "$HOME/.local/bin/ttmux.bash-backup"
printf 'old poke\n' > "$HOME/.local/bin/ttmux-poke"
printf 'old completion\n' > "$HOME/.bash_completion.d/ttmux"
ln -s roami "$HOME/.local/bin/ttmux"
source "$REPO_DIR/scripts/install/retire-session-entries.sh"
retire_roami_session_entries "$HOME/.local/bin"
bash "$REPO_DIR/skills/sync-skills.sh" > /dev/null
[[ ! -e "$HOME/.local/bin/ttmux" && ! -L "$HOME/.local/bin/ttmux" ]]
[[ ! -e "$HOME/.local/bin/ttmux.bash-backup" && ! -e "$HOME/.local/bin/ttmux-poke" ]]
[[ ! -e "$HOME/.bash_completion.d/ttmux" && ! -e "$HOME/.claude/skills/ttmux" ]]
[[ -s "$HOME/.claude/skills/roami-session/SKILL.md" && -s "$HOME/.codex/skills/roami-session/SKILL.md" ]]
[[ "$(find "$FIXTURE/archive" -type f | wc -l)" -ge 4 ]]
retire_roami_session_entries "$HOME/.local/bin"
bash "$REPO_DIR/skills/sync-skills.sh" > /dev/null
printf 'PASS: legacy entries archived outside PATH; Roami skill installed; repeated migration is safe\n'
