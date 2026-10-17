#!/usr/bin/env bash
#
# skills/sync-skills.sh — 把仓库 skills/ 安装到 Claude Code 与 Codex 的技能目录。
#
# 单一真源：install.sh(本地分支) 与 start.sh --dev(开发模式) 共用这套合并逻辑，
# 避免两处重复。curl|bash 安装(无本地文件)时 install.sh 走自己的 GitHub 下载分支。
#
#   用法: bash skills/sync-skills.sh [Claude技能目录]   # 默认 ~/.claude/skills
#   存在 ~/.codex 时，会一并同步到 ~/.codex/skills（codex 成员/指挥也能用）。
#
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # 仓库 skills/ 目录
DEST="${1:-${HOME}/.claude/skills}"

# 目标技能目录：Claude + (存在则) Codex。两者都用目录形式 <名>/SKILL.md，
# 扁平 <名>.md 不被 Claude Code v2.1+ 识别（会报「Unknown command: /<名>」）。
TARGETS=("$DEST")
[[ -d "${HOME}/.codex" ]] && TARGETS+=("${HOME}/.codex/skills")

# 子文档拼接顺序；与 scripts/install/install-ttmux.sh 的 GitHub 下载分支保持一致。
CC_SWARM_DOCS="intake decompose spawn patrol approve test-push review concurrency integrate memory"
DEV_ROLES_DOCS="plaza board chrome pm architect frontend backend fullstack qa designer reviewer devops docs"

# 把一个 skill 的 SKILL.md + docs/<doc>.md 合并到 $1（输出文件）。
merge_skill() {  # <out> <skill名> <doc顺序…>
    local out="$1" name="$2"; shift 2
    [[ -f "${SRC}/${name}/SKILL.md" ]] || return 0
    cat "${SRC}/${name}/SKILL.md" > "$out"
    local doc f
    for doc in "$@"; do
        f="${SRC}/${name}/docs/${doc}.md"; [[ -f "$f" ]] || f="${SRC}/${name}/${doc}.md"
        [[ -f "$f" ]] && { printf '\n\n' >> "$out"; cat "$f" >> "$out"; }
    done
}

# cc-swarm / dev-roles：SKILL.md + docs/*.md 先合并到临时文件，再分发到各目标。
tmp_cc="$(mktemp)"; merge_skill "$tmp_cc" cc-swarm $CC_SWARM_DOCS
tmp_dr="$(mktemp)"; merge_skill "$tmp_dr" dev-roles $DEV_ROLES_DOCS

for d in "${TARGETS[@]}"; do
    mkdir -p "$d"
    rm -f "${d}/ttmux.md" "${d}/cc-swarm.md"   # 清掉历史遗留的扁平文件
    # roami session skill：单文件（chrome CLI 不单独建技能，由 cc-swarm 的 CLI 列表引用）
    if [[ -f "${SRC}/ttmux/SKILL.md" ]]; then
        mkdir -p "${d}/ttmux"
        cp "${SRC}/ttmux/SKILL.md" "${d}/ttmux/SKILL.md"
    fi
    # cc-swarm skill
    if [[ -s "$tmp_cc" ]]; then
        mkdir -p "${d}/cc-swarm"
        cp "$tmp_cc" "${d}/cc-swarm/SKILL.md"
    fi
    # dev-roles skill（SKILL.md + 各角色子文档合并；供 swarm leader 拆班子）
    if [[ -s "$tmp_dr" ]]; then
        mkdir -p "${d}/dev-roles"
        cp "$tmp_dr" "${d}/dev-roles/SKILL.md"
    fi
    # babysit-pr skill：SKILL.md + 同目录脚本 wait-codex-review.sh 一并拷贝
    if [[ -f "${SRC}/babysit-pr/SKILL.md" ]]; then
        mkdir -p "${d}/babysit-pr"
        cp "${SRC}/babysit-pr/SKILL.md" "${d}/babysit-pr/SKILL.md"
        cp "${SRC}/babysit-pr/wait-codex-review.sh" "${d}/babysit-pr/wait-codex-review.sh"
        chmod +x "${d}/babysit-pr/wait-codex-review.sh"
    fi
    echo "✔ skills 已同步到 ${d} (ttmux, cc-swarm, dev-roles, babysit-pr)"
done
rm -f "$tmp_cc" "$tmp_dr"
