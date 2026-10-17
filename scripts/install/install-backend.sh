# scripts/install/install-backend.sh — [3/3] 构建后端服务产物（前端 dist + 后端二进制）。
# 只构建、不启动：启动交给 start.sh（bash start.sh 直接起；--dev 每次重编）。
# 仅本地 checkout 可用；curl|bash 远程无源码则跳过。
# 依赖：lib/common, lib/platform；编排器导出 SCRIPT_DIR。环境开关 TTMUX_SKIP_BACKEND=1 跳过。
# shellcheck shell=bash

ensure_go() {
    command -v go &>/dev/null && return 0
    if can_autoinstall; then
        step "未检测到 Go，自动安装中 (${PKG})..."
        pkg_do go || true
    fi
    command -v go &>/dev/null
}

backend_build() {
    # 前端：缺依赖先 npm install，再 vite build → frontend/dist
    if [ ! -d "${SCRIPT_DIR}/frontend/node_modules" ]; then
        step "安装前端依赖 (npm install)..."
        (cd "${SCRIPT_DIR}/frontend" && npm install)
    fi
    step "构建前端 (vite build) → frontend/dist..."
    (cd "${SCRIPT_DIR}/frontend" && npx vite build)
    # 后端：go build → backend/ttmux-web
    step "构建后端 (go build) → backend/ttmux-web..."
    (cd "${SCRIPT_DIR}" && go build -o backend/ttmux-web ./cmd/roami)
}

module_backend() {
    head2 "[3/3] 构建后端服务 (ttmux-web)"
    if [[ "${TTMUX_SKIP_BACKEND:-0}" == "1" ]]; then
        warn "TTMUX_SKIP_BACKEND=1，跳过后端构建（仅装 CLI/chrome）"; return 0
    fi
    if [[ ! -d "${SCRIPT_DIR}/backend" || ! -d "${SCRIPT_DIR}/frontend" ]]; then
        warn "无后端/前端源码(非本地 checkout)，跳过。克隆仓库后运行: bash install.sh"; return 0
    fi
    if ! ensure_go; then
        warn "缺少 Go，无法构建后端：$(pkg_cmd go)（或装官方版 https://go.dev/dl/）"; return 0
    fi
    go_ver_ok || warn "Go 版本偏低，项目需 ≥ 1.22；过低会构建失败，建议装官方版 https://go.dev/dl/"
    if ! command -v npm &>/dev/null; then
        warn "缺少 npm，无法构建前端：$(pkg_cmd node)"; return 0
    fi
    if backend_build; then
        info "后端已构建：backend/ttmux-web + frontend/dist"
        echo -e "      ${dim}启动:  bash start.sh         （直接启动已构建产物）${reset}"
        echo -e "      ${dim}开发:  bash start.sh --dev   （每次重新编译再启动）${reset}"
    else
        warn "后端构建失败，可手动重试: bash start.sh --dev"
    fi
}
