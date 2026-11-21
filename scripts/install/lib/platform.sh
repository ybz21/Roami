# scripts/install/lib/platform.sh — 平台/架构检测 + 包管理辅助。source 时自动跑检测。
# 暴露变量：OS(mac|wsl|linux|other) IS_WSL PKG(apt|dnf|pacman|brew) SUDO ARCH_H PLAT_H
# 暴露函数：can_autoinstall pkg_cmd pkg_do go_ver_ok
# shellcheck shell=bash

detect_platform() {
    OS="other"; IS_WSL=0; PKG=""
    case "$(uname -s)" in
        Darwin) OS="mac"; command -v brew &>/dev/null && PKG="brew" ;;
        Linux)
            OS="linux"
            if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null || [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
                OS="wsl"; IS_WSL=1
            fi
            if   command -v apt-get &>/dev/null; then PKG="apt"
            elif command -v dnf     &>/dev/null; then PKG="dnf"
            elif command -v pacman  &>/dev/null; then PKG="pacman"
            fi ;;
    esac

    case "$(uname -m)" in
        x86_64|amd64)  ARCH_H="x86_64" ;;
        arm64|aarch64) ARCH_H="arm64" ;;
        *)             ARCH_H="$(uname -m)" ;;
    esac
    case "$OS" in
        mac)   PLAT_H="macOS" ;;
        wsl)   PLAT_H="WSL (${WSL_DISTRO_NAME:-Linux})" ;;
        linux) PLAT_H="Linux" ;;
        *)     PLAT_H="$(uname -s)" ;;
    esac

    SUDO=""
    [[ "$(id -u)" -ne 0 ]] && command -v sudo &>/dev/null && SUDO="sudo"
}

# 能否自动装包：root / 免密 sudo / 交互式终端(允许弹密码)。
# curl|bash 非交互(stdin 是管道)则不自动装，改为打印精确命令，避免卡在密码输入。
can_autoinstall() {
    [[ -n "$PKG" ]] || return 1
    [[ "$PKG" == brew ]] && return 0          # brew 不需要 sudo
    [[ "$(id -u)" -eq 0 ]] && return 0
    [[ -n "$SUDO" ]] || return 1
    sudo -n true 2>/dev/null && return 0       # 免密 sudo
    [[ -t 0 ]]                                 # 交互式终端：允许 sudo 弹密码
}

# 某工具在当前平台的安装命令(仅用于提示)
pkg_cmd() {  # <tmux|node|go>
    case "$1:$PKG" in
        tmux:brew)       echo "brew install tmux" ;;
        tmux:apt)        echo "sudo apt install -y tmux" ;;
        tmux:dnf)        echo "sudo dnf install -y tmux" ;;
        tmux:pacman)     echo "sudo pacman -S tmux" ;;
        node:brew)       echo "brew install node" ;;
        node:apt)        echo "sudo apt install -y nodejs npm" ;;
        node:dnf)        echo "sudo dnf install -y nodejs npm" ;;
        node:pacman)     echo "sudo pacman -S nodejs npm" ;;
        go:brew)         echo "brew install go" ;;
        go:apt)          echo "sudo apt install -y golang" ;;
        go:dnf)          echo "sudo dnf install -y golang" ;;
        go:pacman)       echo "sudo pacman -S go" ;;
        *)               echo "请手动安装 $1" ;;
    esac
}

# best-effort 装包；失败返回非零
pkg_do() {  # <tmux|node|go>
    local p=""
    case "$PKG" in
        apt)
            case "$1" in tmux) p=tmux ;; node) p="nodejs npm" ;; go) p=golang ;; esac
            $SUDO apt-get update -qq && $SUDO apt-get install -y $p ;;
        dnf)
            case "$1" in tmux) p=tmux ;; node) p="nodejs npm" ;; go) p=golang ;; esac
            $SUDO dnf install -y $p ;;
        pacman)
            case "$1" in tmux) p=tmux ;; node) p="nodejs npm" ;; go) p=go ;; esac
            $SUDO pacman -S --noconfirm $p ;;
        brew)
            brew install "$1" ;;
        *) return 1 ;;
    esac
}

# go 是否 ≥ 1.22（项目要求）
go_ver_ok() {
    command -v go &>/dev/null || return 1
    local maj min
    read -r maj min < <(go version | sed -E 's/.*go([0-9]+)\.([0-9]+).*/\1 \2/')
    [[ "$maj" -gt 1 || ( "$maj" -eq 1 && "$min" -ge 22 ) ]]
}

detect_platform   # source 即检测
