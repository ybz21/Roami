#!/usr/bin/env bash
#
# Roami 常驻安装器 —— 下载单一自包含二进制并注册为常驻服务（systemd）。适合 24 小时运行的机器。
#
# 一行安装（推荐）：
#   curl -fsSL https://raw.githubusercontent.com/ybz21/Roam/main/install.sh | bash
#
# roami 是自包含二进制（内嵌前端与会话核心），目标机无需 go/node/npm。
# 配置与数据都在 ~/.roami/（首次启动自动生成 config.yaml）。首次打开网页设置登录口令。
#
# 环境开关：
#   ROAMI_VERSION=vX.Y.Z   指定版本（默认 latest）
#   ROAMI_BIN_DIR=DIR      安装目录（默认 ~/.local/bin）
#   ROAMI_NO_SERVICE=1     只装二进制，不注册 systemd 服务
#   ROAMI_SYSTEM=1         注册系统级 systemd 服务（/etc/systemd/system，需 root/sudo）
#   ROAMI_NO_KVM=1         跳过 /dev/kvm 授权（则本机 Android 模拟器起不来）
#   ROAMI_FROM_SOURCE=1    在仓库 clone 内从源码构建（需 go+node），而非下载 release
#
# 开发/源码构建请用 start.sh --dev（会从源码构建 CLI/chrome/skills + 前后端）。
#
set -euo pipefail

REPO="ybz21/Roam"
VERSION="${ROAMI_VERSION:-latest}"
INSTALL_RUN_USER="${SUDO_USER:-$(id -un)}"
INSTALL_RUN_HOME="${HOME}"
if [ "${ROAMI_SYSTEM:-0}" = 1 ] && [ -n "${SUDO_USER:-}" ]; then
  INSTALL_RUN_HOME="$(getent passwd "$INSTALL_RUN_USER" | cut -d: -f6)"
  [ -n "$INSTALL_RUN_HOME" ] || { echo "Cannot resolve service user home" >&2; exit 1; }
fi
BIN_DIR="${ROAMI_BIN_DIR:-${INSTALL_RUN_HOME}/.local/bin}"
SERVICE_NAME="roami"

# ── 输出助手 ─────────────────────────────────────────────────────
if [ -t 1 ]; then
  bold=$'\e[1m'; dim=$'\e[2m'; green=$'\e[32m'; cyan=$'\e[36m'; yellow=$'\e[33m'; reset=$'\e[0m'
else
  bold=''; dim=''; green=''; cyan=''; yellow=''; reset=''
fi
info() { echo -e " ${green}✔${reset} $*"; }
step() { echo -e " ${cyan}●${reset} $*"; }
warn() { echo -e "  ${yellow}⚠ $*${reset}"; }
die()  { echo -e " ✘ $*" >&2; exit 1; }

# ── 平台检测 → release 资产名 roami-<os>-<arch> ───────────────────
detect_asset() {
  local os arch
  case "$(uname -s)" in
    Linux)  os=linux ;;
    Darwin) os=darwin ;;
    *) die "暂不支持的系统: $(uname -s)（支持 Linux / macOS）" ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64)  arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) die "暂不支持的架构: $(uname -m)（支持 amd64 / arm64）" ;;
  esac
  OS="$os"; ASSET="roami-${os}-${arch}"
}

# 解析生效的 release tag：显式 ROAMI_VERSION 直接用；否则优先 stable「latest」，
# 若仓库只有 prerelease（latest 会 404）则退回 GitHub API 取最新一个 release（含 prerelease）。
resolve_tag() {
  [ "$VERSION" != latest ] && { echo "$VERSION"; return; }
  if curl -fsIL -o /dev/null "https://github.com/${REPO}/releases/latest/download/${ASSET}" 2>/dev/null; then
    echo latest; return
  fi
  curl -fsSL "https://api.github.com/repos/${REPO}/releases?per_page=1" 2>/dev/null \
    | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name":[[:space:]]*"([^"]+)".*/\1/'
}

download_url() {  # <tag>
  local tag="$1"
  if [ -z "$tag" ] || [ "$tag" = latest ]; then
    echo "https://github.com/${REPO}/releases/latest/download/${ASSET}"
  else
    echo "https://github.com/${REPO}/releases/download/${tag}/${ASSET}"
  fi
}

# ── 安装二进制：下载 release，或（ROAMI_FROM_SOURCE / 下载失败且在 clone 内）从源码构建 ──
# Inspect the staged release before replacing any live binary or compatibility entry.
preflight_storage() {
  local candidate="$1" report
  chmod +x "$candidate"
  local -a command=("$candidate" db status --json)
  if [ "${ROAMI_SYSTEM:-0}" = 1 ] && [ "$(id -u)" = 0 ] && [ "$INSTALL_RUN_USER" != root ]; then
    command=(runuser -u "$INSTALL_RUN_USER" -- env "HOME=$INSTALL_RUN_HOME" "${command[@]}")
  fi
  if ! report="$("${command[@]}")"; then
    die "存储预检失败；现有安装未替换。检查候选程序: $candidate"
  fi
  if printf '%s' "$report" | grep -Eq '"migrationRequired"[[:space:]]*:[[:space:]]*true'; then
    local pending="${candidate%.tmp}.upgrade"
    mv -f "$candidate" "$pending"
    die "检测到旧数据库布局，现有安装未替换。先停止旧服务与插件写者，用 $pending db migrate --layout --dry-run 盘点，再用 --layout --offline 迁移，完成后重新安装。"
  fi
}

service_path_environment() {
  local prefix suffix key value
  local format="${1:-systemd}"
  for prefix in ROAMI ROAM TTMUX; do
    for suffix in HOME DATA CONFIG DATABASE_DIR BACKUP_DIR; do
      key="${prefix}_${suffix}"
      value="${!key:-}"
      [ -n "$value" ] || continue
      if [ "$format" = plist ]; then
        value="${value//&/\&amp;}"
        value="${value//</\&lt;}"
        value="${value//>/\&gt;}"
        printf '<key>%s</key><string>%s</string>\n' "$key" "$value"
        continue
      fi
      value="${value//\\/\\\\}"
      value="${value//\"/\\\"}"
      value="${value//%/%%}"
      printf 'Environment="%s=%s"\n' "$key" "$value"
    done
  done
}

install_binary() {
  mkdir -p "$BIN_DIR"
  local dest="${BIN_DIR}/roami"

  if [ "${ROAMI_FROM_SOURCE:-0}" != 1 ]; then
    local tag url; tag="$(resolve_tag)"; url="$(download_url "$tag")"
    step "下载 ${ASSET} (${tag:-latest})..."
    if curl -fSL --progress-bar -o "${dest}.tmp" "$url"; then
      preflight_storage "${dest}.tmp"
      mv "${dest}.tmp" "$dest"; chmod +x "$dest"
      link_legacy_name "$dest"
      info "roami 已安装到 $dest"
      return 0
    fi
    rm -f "${dest}.tmp"
    warn "下载失败（可能该 release 尚未发布）。"
  fi

  # 源码构建回退（需在 clone 内，且有 go+node）
  local here; here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
  if [ -f "${here}/scripts/build/build-roami.sh" ] && command -v go >/dev/null && command -v npm >/dev/null; then
    step "从源码构建 roami（scripts/build/build-roami.sh）..."
    ( cd "$here" && bash scripts/build/build-roami.sh )
    local built="${here}/backend/dist/${ASSET}"
    [ -f "$built" ] || die "源码构建未产出当前平台二进制"
    # 服务正跑着时 cp 直接覆盖会报「文本文件忙」；先落临时名再 mv，rename 对运行中的二进制是原子的
    cp "$built" "${dest}.tmp"; chmod +x "${dest}.tmp"
    preflight_storage "${dest}.tmp"
    mv -f "${dest}.tmp" "$dest"
    link_legacy_name "$dest"
    info "roami 已从源码构建并安装到 $dest"
    return 0
  fi
  die "无法安装 roami：下载失败且非源码环境（需 clone 仓库 + go/npm，或先发布 release）"
}

# ── tmux（会话基座）：roami 内置会话核心，但会话/蜂群仍需宿主机的 tmux ─────
ensure_tmux() {
  command -v tmux >/dev/null && { info "tmux 已就绪"; return 0; }
  local sudo=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null && sudo=sudo
  step "未检测到 tmux，尝试自动安装（可能需要 sudo 口令）..."
  if   command -v apt-get >/dev/null; then $sudo apt-get update -qq && $sudo apt-get install -y -qq tmux
  elif command -v dnf     >/dev/null; then $sudo dnf install -y tmux
  elif command -v yum     >/dev/null; then $sudo yum install -y tmux
  elif command -v pacman  >/dev/null; then $sudo pacman -Sy --noconfirm tmux
  elif command -v zypper  >/dev/null; then $sudo zypper -n install tmux
  elif command -v apk     >/dev/null; then $sudo apk add tmux
  elif command -v brew    >/dev/null; then brew install tmux
  fi
  command -v tmux >/dev/null && info "tmux 已安装" || warn "tmux 未安装：会话/蜂群功能需要它，请手动安装后重试"
}

# ── Chromium（「浏览器」镜像页需要一台 Chrome/Chromium 才能投屏）─────
# roami 后端按 google-chrome → chromium → chromium-browser 的顺序在 PATH 里探测，
# 都没有就会「拉起 Chrome 失败」。ROAMI_NO_CHROME=1 可跳过（则浏览器镜像页不可用）。
ensure_chrome() {
  [ "${ROAMI_NO_CHROME:-0}" = 1 ] && { step "ROAMI_NO_CHROME=1：跳过 Chromium（浏览器镜像页将不可用）"; return 0; }
  if command -v google-chrome >/dev/null || command -v chromium >/dev/null || command -v chromium-browser >/dev/null; then
    info "Chrome/Chromium 已就绪（浏览器镜像可用）"; return 0
  fi
  local sudo=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null && sudo=sudo
  step "未检测到 Chrome/Chromium，尝试安装 Chromium（较大；ROAMI_NO_CHROME=1 可跳过）..."
  if   command -v apt-get >/dev/null; then
    $sudo apt-get install -y -qq chromium 2>/dev/null \
      || $sudo apt-get install -y -qq chromium-browser 2>/dev/null \
      || { command -v snap >/dev/null && $sudo snap install chromium; }
  elif command -v dnf    >/dev/null; then $sudo dnf install -y chromium
  elif command -v pacman >/dev/null; then $sudo pacman -Sy --noconfirm chromium
  elif command -v zypper >/dev/null; then $sudo zypper -n install chromium
  elif command -v apk    >/dev/null; then $sudo apk add chromium
  elif command -v snap   >/dev/null; then $sudo snap install chromium
  elif command -v brew   >/dev/null; then brew install --cask chromium 2>/dev/null || brew install chromium
  fi
  if command -v google-chrome >/dev/null || command -v chromium >/dev/null || command -v chromium-browser >/dev/null; then
    info "Chromium 已安装（浏览器镜像可用）"
  else
    warn "未能自动安装 Chromium：浏览器镜像页不可用。装好后 roami 会自动探测，或设 CHROME_BIN 指向可执行文件；重启：systemctl --user restart roami"
  fi
}

# ── adb（「手机」镜像页需要 adb 才能连 Android 设备）─────────────────
# ROAMI_NO_ADB=1 可跳过（则手机镜像页不可用）。
ensure_adb() {
  [ "${ROAMI_NO_ADB:-0}" = 1 ] && { step "ROAMI_NO_ADB=1：跳过 adb（手机镜像页将不可用）"; return 0; }
  command -v adb >/dev/null && { info "adb 已就绪（手机镜像可用）"; return 0; }
  local sudo=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null && sudo=sudo
  step "未检测到 adb，尝试安装（手机镜像页用）..."
  if   command -v apt-get >/dev/null; then $sudo apt-get install -y -qq adb 2>/dev/null || $sudo apt-get install -y -qq android-tools-adb 2>/dev/null
  elif command -v dnf     >/dev/null; then $sudo dnf install -y android-tools
  elif command -v yum     >/dev/null; then $sudo yum install -y android-tools
  elif command -v pacman  >/dev/null; then $sudo pacman -Sy --noconfirm android-tools
  elif command -v zypper  >/dev/null; then $sudo zypper -n install android-tools
  elif command -v apk     >/dev/null; then $sudo apk add android-tools
  elif command -v brew    >/dev/null; then brew install --cask android-platform-tools 2>/dev/null || brew install android-platform-tools
  fi
  command -v adb >/dev/null && info "adb 已安装（手机镜像可用）" \
    || warn "未能自动安装 adb：手机镜像页不可用，装好后重启：systemctl --user restart roami"
}

# ── KVM（本机 Android 模拟器要靠它跑起来）──────────────────────────
#
# 唯一实现在 scripts/install/kvm-access.sh —— 这里按「本地仓库 → 远端同源 → 只打印命令」
# 三级取用，**不留第二份副本**：抄两份必然走散，改一条规则要改两处，最后两个入口
# 按不同版本的规则给同一台机器授权。远端和 install.sh 自己是同一个 raw 源，不多一层信任。
ensure_kvm() {
  [ "$OS" = linux ] || return 0                     # macOS 用 HVF，不碰 /dev/kvm
  [ -e /dev/kvm ] || return 0                       # 云主机大多没有，别为用不上的功能弹口令框
  local here lib=""
  here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
  if [ -n "$here" ] && [ -f "$here/scripts/install/kvm-access.sh" ]; then
    lib="$here/scripts/install/kvm-access.sh"
  else
    lib="$(mktemp)" || lib=""
    # 限时：网络不通时安装器不能卡在这儿 —— 拿不到就退回打印命令，几秒内给出结论。
    if [ -n "$lib" ] && ! curl -fsSL --connect-timeout 5 --max-time 20 \
         "https://raw.githubusercontent.com/${REPO}/main/scripts/install/kvm-access.sh" -o "$lib" 2>/dev/null; then
      rm -f "$lib"; lib=""
    fi
  fi
  if [ -z "$lib" ]; then
    warn "取不到 KVM 授权脚本。若要用本机模拟器，在终端里跑一次： sudo gpasswd -a \$USER kvm && sudo setfacl -m u:\$USER:rw /dev/kvm"
    return 0
  fi
  # shellcheck source=scripts/install/kvm-access.sh
  source "$lib"
  kvm_ensure step
  [ "$lib" = "$here/scripts/install/kvm-access.sh" ] || rm -f "$lib"
}

# 旧名 roam 留一条软链：改名之前写好的脚本、别人的 crontab、自己的手指记忆都还在。
# 已经存在同名**真文件**（旧版二进制）时也换成软链——留着两个二进制只会让人不知道跑的是哪个。
link_legacy_name() {
  local dest="$1" legacy
  local here retirement
  here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
  retirement="${here}/scripts/install/retire-session-entries.sh"
  if [ ! -f "$retirement" ]; then
    retirement="$(mktemp)"
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/${ROAMI_INSTALL_BRANCH:-main}/scripts/install/retire-session-entries.sh" -o "$retirement" || die "无法加载旧入口迁移脚本"
  fi
  source "$retirement"
  retire_roami_session_entries "$BIN_DIR"
  [ "$retirement" = "${here}/scripts/install/retire-session-entries.sh" ] || rm -f "$retirement"
  for legacy in roam chrome; do
    ln -sfn "$dest" "${BIN_DIR}/${legacy}"
  done
  mkdir -p "${HOME}/.local/share/bash-completion/completions"
  "$dest" completion > "${HOME}/.local/share/bash-completion/completions/roami"
  "$dest" session completion
}


# 升级路径：把改名前的 roam.service 停掉再删，否则两个服务抢同一个端口，
# 而且用户会看到一个永远重启失败的 roam.service。
retire_legacy_service() {
  command -v systemctl >/dev/null || return 0
  if systemctl --user list-unit-files roam.service >/dev/null 2>&1 && \
     systemctl --user cat roam.service >/dev/null 2>&1; then
    step "停用改名前的 roam.service（数据与配置已迁移到 ~/.roami）"
    systemctl --user disable --now roam.service >/dev/null 2>&1 || true
    rm -f "${HOME}/.config/systemd/user/roam.service"
    systemctl --user daemon-reload
  fi
}

# ── systemd 常驻服务 ─────────────────────────────────────────────
install_service_user() {
  command -v systemctl >/dev/null || { warn "无 systemd，跳过服务注册；手动运行：${BIN_DIR}/roami"; return 0; }
  retire_legacy_service
  local unit_dir="${HOME}/.config/systemd/user"
  mkdir -p "$unit_dir"
  cat > "${unit_dir}/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Roami web console
After=network-online.target
Wants=network-online.target

[Service]
$(service_path_environment)
ExecStart=${BIN_DIR}/roami
Restart=always
RestartSec=3
# roami 起的 tmux server 在同一个 cgroup 里：默认 KillMode 会在 restart 时连 tmux 一起杀，所有会话当场没了
KillMode=process

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable "${SERVICE_NAME}.service"
  systemctl --user restart "${SERVICE_NAME}.service"   # restart：升级重跑时用新二进制替换旧进程
  # 让用户级服务在未登录时也常驻（服务器场景必需）
  if command -v loginctl >/dev/null; then
    loginctl enable-linger "$USER" 2>/dev/null || warn "loginctl enable-linger 失败：注销后服务可能停止（可 sudo loginctl enable-linger $USER）"
  fi
  info "已注册用户级 systemd 服务：systemctl --user status ${SERVICE_NAME}"
}

install_service_system() {
  command -v systemctl >/dev/null || die "无 systemd，无法注册系统级服务"
  local sudo=""; [ "$(id -u)" -ne 0 ] && sudo="sudo"
  local user="$INSTALL_RUN_USER" service_home="$INSTALL_RUN_HOME"
  $sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=Roami web console
After=network-online.target
Wants=network-online.target

[Service]
User=${user}
Environment=HOME=${service_home}
$(service_path_environment)
ExecStart=${BIN_DIR}/roami
Restart=always
RestartSec=3
# roami 起的 tmux server 在同一个 cgroup 里：默认 KillMode 会在 restart 时连 tmux 一起杀，所有会话当场没了
KillMode=process

[Install]
WantedBy=multi-user.target
EOF
  $sudo systemctl daemon-reload
  $sudo systemctl enable "${SERVICE_NAME}.service"
  $sudo systemctl restart "${SERVICE_NAME}.service"   # restart：升级重跑时用新二进制替换旧进程
  info "已注册系统级 systemd 服务：sudo systemctl status ${SERVICE_NAME}"
}

# macOS：用 launchd（LaunchAgent）常驻，开机自启 + 崩溃重拉。
install_service_launchd() {
  local plist="${HOME}/Library/LaunchAgents/com.roami.console.plist"
  mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/.roami"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.roami.console</string>
  <key>ProgramArguments</key><array><string>${BIN_DIR}/roami</string></array>
  <key>EnvironmentVariables</key><dict>
$(service_path_environment plist)
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${HOME}/.roami/roami.log</string>
  <key>StandardErrorPath</key><string>${HOME}/.roami/roami.log</string>
</dict>
</plist>
EOF
  launchctl unload "$plist" 2>/dev/null || true
  if launchctl load "$plist" 2>/dev/null; then
    info "已注册 launchd 服务：launchctl {unload|load} ${plist}（日志 ~/.roami/roami.log）"
  else
    warn "launchctl load 失败，可手动运行：${BIN_DIR}/roami"
  fi
}

# ── 主流程 ───────────────────────────────────────────────────────
echo ""
echo -e "  ${bold}Roami${reset} ${dim}— 常驻安装（下载二进制 + systemd/launchd 常驻）${reset}"
echo ""

detect_asset
install_binary
ensure_tmux
ensure_chrome
ensure_adb
ensure_kvm

if [ "${ROAMI_NO_SERVICE:-0}" = 1 ]; then
  step "ROAMI_NO_SERVICE=1：跳过服务注册"
elif [ "${ROAMI_SYSTEM:-0}" = 1 ]; then
  install_service_system
elif [ "$OS" = darwin ]; then
  install_service_launchd
else
  install_service_user
fi

# PATH 提示
if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
  echo ""; warn "${BIN_DIR} 不在 PATH，请追加： export PATH=\"${BIN_DIR}:\$PATH\""
fi

PORT="13579"
echo ""
echo -e "  ${bold}完成!${reset}"
echo -e "  ${dim}控制台:${reset} https://<本机IP>:${PORT}  ${dim}(默认自签 HTTPS；设 web.tls: false 退回 http)${reset}"
echo -e "  ${dim}首次打开网页需设置登录口令；配置在 ~/.roami/config.yaml${reset}"
if [ "${ROAMI_NO_SERVICE:-0}" != 1 ]; then
  if [ "$OS" = darwin ]; then
    echo -e "  ${dim}服务:${reset} launchctl {unload|load} ~/Library/LaunchAgents/com.roami.console.plist"
  else
    echo -e "  ${dim}服务:${reset} systemctl --user {status|restart|stop} ${SERVICE_NAME}   ${dim}(或系统级 sudo systemctl …)${reset}"
  fi
fi
echo ""
