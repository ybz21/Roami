# scripts/install/install-roami.sh — [1/3] Roami CLI 二进制 + skills + Tab 补全。
# 依赖：lib/common, lib/platform, lib/github；编排器导出 GO_SRC/SKILL_DIR/CC_SWARM_DOCS/INSTALL_DIR/REPO/BRANCH。
# shellcheck shell=bash

source "${SCRIPT_DIR}/scripts/install/retire-session-entries.sh"

roami_bin() {
    mkdir -p "$INSTALL_DIR"
    if [[ -f "${GO_SRC}/go.mod" ]]; then
        (cd "$GO_SRC" && CGO_ENABLED=0 go build -o "${INSTALL_DIR}/roami" ./cmd/roami)
    elif [[ ! -x "${INSTALL_DIR}/roami" ]]; then
        download_asset roami "roami-$(release_target)" || die "Roami download failed"
    fi
    retire_roami_session_entries "$INSTALL_DIR"
    ln -sf roami "${INSTALL_DIR}/roam"
}

roami_skills() {
    mkdir -p "$SKILL_DIR"
    if [[ -f "${SCRIPT_DIR}/skills/sync-skills.sh" ]]; then
        # 本地安装：复用 skills/sync-skills.sh（与开发模式 start.sh --dev 同一套合并逻辑）
        bash "${SCRIPT_DIR}/skills/sync-skills.sh" "$SKILL_DIR" >/dev/null && info "skills 已安装 (roami-session, cc-swarm, dev-roles, babysit-pr)"
        return 0
    fi
    # curl|bash 无本地文件：从 GitHub 下载合并。
    # 技能须为目录形式 <名>/SKILL.md（扁平 <名>.md 不被 Claude Code v2.1+ 识别）。
    # 目标：Claude + (存在则) Codex —— codex 成员/指挥也能用。
    local SKILL_TARGETS=("$SKILL_DIR")
    [[ -d "${HOME}/.codex" ]] && SKILL_TARGETS+=("${HOME}/.codex/skills")

    local local_tmp; local_tmp=$(mktemp -d); local all_ok=true
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/roami-session/SKILL.md" \
        -o "${local_tmp}/roami-session.md" 2>/dev/null || all_ok=false
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/cc-swarm/SKILL.md" \
        -o "${local_tmp}/cc-swarm.md" 2>/dev/null || all_ok=false
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/dev-roles/SKILL.md" \
        -o "${local_tmp}/dev-roles.md" 2>/dev/null || all_ok=false
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/babysit-pr/SKILL.md" \
        -o "${local_tmp}/babysit-pr.md" 2>/dev/null || all_ok=false
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/babysit-pr/wait-codex-review.sh" \
        -o "${local_tmp}/wait-codex-review.sh" 2>/dev/null || all_ok=false
    local d
    for d in $CC_SWARM_DOCS; do
        $all_ok || break
        curl -fsSL "https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/cc-swarm/docs/${d}.md" \
            -o "${local_tmp}/doc-${d}.md" 2>/dev/null && \
            { printf '\n\n' >> "${local_tmp}/cc-swarm.md"; cat "${local_tmp}/doc-${d}.md" >> "${local_tmp}/cc-swarm.md"; }
    done
    # dev-roles 各角色子文档（顺序与 skills/sync-skills.sh 的 DEV_ROLES_DOCS 保持一致）
    for d in plaza board chrome pm architect frontend backend fullstack qa designer reviewer devops docs; do
        $all_ok || break
        curl -fsSL "https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/dev-roles/docs/${d}.md" \
            -o "${local_tmp}/dr-${d}.md" 2>/dev/null && \
            { printf '\n\n' >> "${local_tmp}/dev-roles.md"; cat "${local_tmp}/dr-${d}.md" >> "${local_tmp}/dev-roles.md"; }
    done
    if $all_ok; then
        local sd
        for sd in "${SKILL_TARGETS[@]}"; do
            mkdir -p "$sd"
            rm -f "${sd}/cc-swarm.md"   # 清历史扁平文件
            mkdir -p "${sd}/roami-session" "${sd}/cc-swarm" "${sd}/dev-roles" "${sd}/babysit-pr"
            retire_roami_session_skill "$sd"
            cp "${local_tmp}/roami-session.md" "${sd}/roami-session/SKILL.md"
            cp "${local_tmp}/cc-swarm.md" "${sd}/cc-swarm/SKILL.md"
            cp "${local_tmp}/dev-roles.md" "${sd}/dev-roles/SKILL.md"
            cp "${local_tmp}/babysit-pr.md" "${sd}/babysit-pr/SKILL.md"
            cp "${local_tmp}/wait-codex-review.sh" "${sd}/babysit-pr/wait-codex-review.sh"
            chmod +x "${sd}/babysit-pr/wait-codex-review.sh"
        done
        info "skills 已安装 (roami-session, cc-swarm, dev-roles, babysit-pr)"
    fi
    rm -rf "$local_tmp"
}

roami_completion() {
    step "安装 Tab 补全..."
    mkdir -p "${HOME}/.local/share/bash-completion/completions"
    "${INSTALL_DIR}/roami" completion > "${HOME}/.local/share/bash-completion/completions/roami"
    "${INSTALL_DIR}/roami" session completion
}

module_roami() {
    head2 "[1/3] 部署 Roami"
    roami_bin
    roami_skills
    roami_completion
}
