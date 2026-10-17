#!/usr/bin/env bash
# start.sh — 启动 ttmux-web（后台守护，关终端/Ctrl-C 不影响）
#
#   bash start.sh            直接启动已构建的产物（不重新编译，最快）
#   bash start.sh --dev      开发模式：从源码构建 CLI/chrome/skills + 增量编译前端+后端再启动
#                            （原 install.sh 的源码构建编排已并入本脚本；install.sh 现只做「下载二进制 + systemd 常驻」）
#   bash start.sh stop       停止
#   bash start.sh status     查看状态
#   bash start.sh logs       跟随日志
#   bash start.sh fg         前台运行（调试用，Ctrl-C 即停）；可与 --dev 同用
#
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"
export LANG="${LANG:-en_US.UTF-8}"

# ── 解析 --dev（与子命令分离）────────────────────────────────────
DEV=0; ARGS=()
for a in "$@"; do
  case "$a" in
    --dev|-dev|dev) DEV=1 ;;
    *) ARGS+=("$a") ;;
  esac
done
if [ ${#ARGS[@]} -gt 0 ]; then set -- "${ARGS[@]}"; else set --; fi

# ── 配置：加载 .env（已存在的环境变量优先）──────────────────────
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    [ "${line#*=}" = "$line" ] && continue
    key="${line%%=*}"; key="$(echo "$key" | tr -d '[:space:]')"
    [ -z "$(eval "echo \${$key:-}")" ] && export "$key=${line#*=}"
  done < .env
fi

BIND="${TTMUX_WEB_BIND:-0.0.0.0:13579}"
PORT="${BIND##*:}"
# 登录口令在子命令(stop/status/logs)处理之后再解析，避免这些操作也触发生成/写 .env。
# 自签 HTTPS：默认开启。手机经局域网用麦克风(语音)/剪贴板(一键粘贴)需「安全上下文」，
# 纯 http 会被浏览器禁用这些能力。设 TTMUX_WEB_TLS=0 可退回 http。证书由后端就地生成。
export TTMUX_WEB_TLS="${TTMUX_WEB_TLS:-1}"
case "$(echo "${TTMUX_WEB_TLS}" | tr 'A-Z' 'a-z')" in
  0|off|false|no) export TTMUX_WEB_TLS=0; SCHEME=http ;;
  *)              export TTMUX_WEB_TLS=1; SCHEME=https ;;
esac
OS="$(uname -s 2>/dev/null || echo unknown)"

lan_ip() {
  if [ "$OS" = "Darwin" ]; then
    ipconfig getifaddr en0 2>/dev/null \
      || ipconfig getifaddr en1 2>/dev/null \
      || route -n get default 2>/dev/null | awk '/interface:/{print $2}' | xargs -I{} ipconfig getifaddr {} 2>/dev/null \
      || true
  else
    hostname -I 2>/dev/null | awk '{print $1}' || true
  fi
}

daemon_start() {
  if command -v setsid >/dev/null 2>&1; then
    setsid "$@" </dev/null >>"$LOG" 2>&1 &
  else
    nohup "$@" </dev/null >>"$LOG" 2>&1 &
  fi
}

LAN=$(lan_ip)
LOG="${TTMUX_WEB_LOG:-/tmp/ttmux-web.log}"
PIDFILE="${TTMUX_WEB_PID:-/tmp/ttmux-web.pid}"

# 找当前监听 PORT 的进程
port_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$PORT" 2>/dev/null || true
  fi
}

# ── 子命令：stop / status / logs（不分 dev/非 dev）────────────────
case "${1:-}" in
  stop)
    pids="$(port_pids)"
    [ -f "$PIDFILE" ] && pids="$pids $(cat "$PIDFILE" 2>/dev/null || true)"
    pids="$(echo $pids | tr ' ' '\n' | sort -u | tr '\n' ' ')"
    if [ -z "${pids// /}" ]; then echo "ttmux-web 未在运行"; else
      echo "==> 停止 ttmux-web ($pids)"
      kill $pids 2>/dev/null || true; sleep 1; kill -9 $pids 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
    exit 0 ;;
  status)
    pids="$(port_pids)"
    if [ -n "${pids// /}" ]; then echo "ttmux-web 运行中 :$PORT (pid $pids)"; else echo "ttmux-web 未运行"; fi
    exit 0 ;;
  logs)
    exec tail -n 100 -f "$LOG" ;;
esac

# ── 登录口令：由后端从 ~/.roami/config.yaml 管理。留空则首次打开网页时在界面上设置；
#    也可编辑 config.yaml 的 web.password，或用「设置 → 修改登录口令」。
#    这里不再生成/写回口令，避免用环境变量覆盖掉「首次设置」流程。
BIN=backend/ttmux-web

# ── dev：从源码刷新 ttmux CLI + chrome + skills ─────────────────────
# 原 install.sh 的源码构建编排已并入这里（后端/前端由本脚本下面自行增量编译）。
if [ "$DEV" = 1 ] && [ -d scripts/install ]; then
  echo "==> [dev] 从源码刷新 ttmux CLI + chrome + skills..."
  SRC="$(pwd)"
  export SCRIPT_DIR="$SRC"
  export GO_SRC="$SRC"
  export CHROME_BUILD="$SRC/scripts/build/build-chrome.sh"
  export INSTALL_DIR="$HOME/.local/bin"
  export SKILL_DIR="$HOME/.claude/skills"
  export REPO="ybz21/Roam" BRANCH="${TTMUX_INSTALL_BRANCH:-main}"
  export CC_SWARM_DOCS="intake decompose spawn patrol approve test-push review concurrency integrate memory"
  mkdir -p "$INSTALL_DIR"
  # lib/platform.sh 在 source 时自检平台；模块用 lib 里的 step/info/… + 平台变量。
  source scripts/install/lib/common.sh
  source scripts/install/lib/platform.sh
  source scripts/install/lib/github.sh
  source scripts/install/install-ttmux.sh
  source scripts/install/install-chrome.sh
  module_ttmux
  module_chrome
fi

# ── 前端依赖：仅目录存在不代表依赖完整 ───────────────────────────
# node_modules 可能是旧的：package.json 新增依赖后（如 @monaco-editor/react）
# 若只判断目录是否存在就会跳过安装，vite build 随即因找不到新依赖而失败。
# 因此当 node_modules 缺失，或 package-lock.json/package.json 比 node_modules 新时，重新安装。
ensure_frontend_deps() {
  if [ ! -d node_modules ]; then
    echo "==> 安装前端依赖..."
    npm install
  elif [ package-lock.json -nt node_modules ] || [ package.json -nt node_modules ]; then
    echo "==> 检测到依赖清单变更，重新安装前端依赖..."
    npm install
  fi
}
export -f ensure_frontend_deps  # 供 (cd frontend && ...) 子 shell 调用

# ── 前端：dev 增量编译；非 dev 直接用 install.sh 产物 ─────────────
if [ "$DEV" = 1 ]; then
  cd frontend
  ensure_frontend_deps
  if [ ! -f dist/index.html ] || [ "$(find src index.html vite.config.ts -newer dist/index.html 2>/dev/null | head -1)" ]; then
    echo "==> 编译前端 (frontend/)..."
    # 走 npm run build 而不是裸 npx vite build：堆上限(NODE_OPTIONS)、i18n/hover 守门、
    # 产物预压缩(.gz) 都定义在 package.json 那一处。绕过去就会各缺一块——
    # 尤其是堆上限：会话有了内存护栏之后，Node 会按 cgroup 限额把默认堆砍到 2GB，
    # 这个前端(monaco 4.3M + mermaid 3.4M)当场 OOM。
    npm run build
    echo "==> 前端编译完成 → frontend/dist/"
  else
    echo "==> 前端无变更，跳过编译"
  fi
  cd ..
elif [ ! -f frontend/dist/index.html ]; then
  echo "==> 未找到 frontend/dist，自动编译前端..."
  (cd frontend && ensure_frontend_deps && npm run build)
elif [ "$(find frontend/src frontend/index.html frontend/vite.config.ts -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
  echo "==> 检测到前端源码变更，自动重新编译..."
  (cd frontend && ensure_frontend_deps && npm run build)
fi

# ── 后端：源码比二进制新时编译；纯安装包继续用 install.sh 产物 ─────────────
build_backend() {
  local version
  version="$(git describe --tags --always --dirty 2>/dev/null || echo dev)"
  go build -ldflags "-X main.version=${version}" -o backend/ttmux-web.next ./cmd/roami || {
    rm -f backend/ttmux-web.next
    return 1
  }
  mv backend/ttmux-web.next "$BIN"
}
if [ "$DEV" = 1 ]; then
  # 检测 .go 与 go:embed 的资源(*.tmpl/*.html)变更，避免改模板却跳过编译
  if [ ! -f "$BIN" ] || [ "$(find backend cmd internal pkg plugins \( -name '*.go' -o -name '*.tmpl' -o -name '*.html' \) -newer "$BIN" 2>/dev/null | head -1)" ]; then
    echo "==> 编译后端..."
    build_backend
  else
    echo "==> 后端无变更，跳过编译"
  fi
elif [ ! -x "$BIN" ]; then
  echo "✘ 未找到 $BIN —— 先构建：bash install.sh   或   bash start.sh --dev"; exit 1
elif [ -d backend/api ] && [ "$(find backend cmd internal pkg plugins \( -name '*.go' -o -name '*.tmpl' -o -name '*.html' \) -newer "$BIN" 2>/dev/null | head -1)" ]; then
  echo "==> 检测到后端源码变更，自动重新编译..."
  build_backend
fi

# ── KVM：--dev 才动手拿权限，平时只提醒 ──────────────────────────
#
# 为什么分开：systemd 的 ExecStart 就是 `start.sh fg`，普通启动也常在后台跑，
# 那里弹 sudo 口令框会把启动挂死（kvm_ensure 里的 can_elevate 也会挡住，
# 但「启动服务」这件事本来就不该顺手要 root）。--dev 是源码档的安装+构建模式，
# 装依赖、编 CLI、拉 chrome 都在那儿，拿 KVM 权限是同一类事。
#
# 只对「装了 Android SDK 却开不了 /dev/kvm」的机器说：没装 SDK 的机器不关心模拟器。
kvm_step() {
  [ "$OS" = Linux ] || return 0
  [ -e /dev/kvm ] || return 0
  [ -r /dev/kvm ] && [ -w /dev/kvm ] && return 0
  local sdk="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}"
  [ -d "$sdk" ] || return 0
  if [ "$DEV" = 1 ] && [ -f scripts/install/kvm-access.sh ]; then
    # shellcheck source=scripts/install/kvm-access.sh
    source scripts/install/kvm-access.sh
    kvm_ensure 'echo "==>"'
    return 0
  fi
  echo "==> 提示：无权访问 /dev/kvm，本机 Android 模拟器起不来。跑一次即可（只需一次）："
  echo "    sudo gpasswd -a \$USER kvm && sudo setfacl -m u:\$USER:rw /dev/kvm"
  echo "    或 bash start.sh --dev 让它替你办（需要在终端里跑）"
}
kvm_step

# ── 启动 ─────────────────────────────────────────────────────────
echo "==> 启动 Roami  $SCHEME://$BIND"
echo "    登录口令：首次打开网页时在界面上设置；或编辑 ~/.roami/config.yaml 的 web.password。"
[ -n "$LAN" ] && echo "==> 手机/平板（同 WiFi）: $SCHEME://$LAN:$PORT"
[ "$SCHEME" = https ] && echo "    （自签证书：手机首次访问点「高级 → 继续前往」即可，之后语音/剪贴板可用；如需 http 设 TTMUX_WEB_TLS=0）"

# ── 装了开机自启就交给 systemd ───────────────────────────────────
#
# scripts/dev/install-autostart.sh 之后服务归 systemd 管，而它跑的正是
# `start.sh fg`——参数一模一样，只是换了谁来拉。这时若还自己 daemon_start，
# 就是两套东西抢同一个端口：下面那段先把 systemd 的进程杀了，新进程占了口，
# systemd 见 MainPID 没了按 Restart=always 又拉一个回来，来回打架。
#
# 判据用 is-enabled 而不是 is-active：装没装自启是既定事实，而 is-active
# 在这一刻可能正好是 activating（服务刚被谁重启），那就漏判了。
# **必须排除 fg**：systemd 的 ExecStart 就是 `start.sh fg`，不排除的话它一进来
# 又去 restart 自己，systemd 数到 start-limit-hit 直接把服务判死（实测踩过）。
if [ "${1:-}" != "fg" ] && command -v systemctl >/dev/null 2>&1 \
   && systemctl --user is-enabled roami.service >/dev/null 2>&1; then
  echo "==> 交给 systemd 重启（roami.service）"
  systemctl --user restart roami.service
  sleep 2
  echo "==> 服务 $(systemctl --user is-active roami.service)  ·  $SCHEME://$BIND"
  echo "    日志: journalctl --user -u roami.service -f   停止: systemctl --user stop roami"
  exit 0
fi

# ── 杀掉旧进程 ───────────────────────────────────────────────────
pids="$(port_pids)"
if [ -n "${pids// /}" ]; then
  echo "==> 杀掉 :$PORT 上的旧进程 ($pids)"
  kill $pids 2>/dev/null || true
  sleep 1
  kill -9 $pids 2>/dev/null || true
fi

# fg：前台运行（调试，Ctrl-C 即停）
if [ "${1:-}" = "fg" ]; then
  shift
  exec "$BIN" -web "$(pwd)/frontend/dist" -addr "$BIND" "$@"
fi

# 默认：后台守护。Linux 优先 setsid；macOS 无 setsid 时使用 nohup。
daemon_start "$BIN" -web "$(pwd)/frontend/dist" -addr "$BIND" "$@"
sleep 1
pids="$(port_pids)"
[ -n "${pids// /}" ] && echo "$pids" | tr ' ' '\n' | head -1 > "$PIDFILE"
echo "==> 已后台守护运行（日志: ${LOG}）"
echo "    停止: bash start.sh stop   状态: bash start.sh status   日志: bash start.sh logs"
