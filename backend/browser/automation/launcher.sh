#!/usr/bin/env bash
#
# roami chrome — 浏览器自动化 CLI（Playwright over CDP）
# https://github.com/ybz21/ttmux
#
# 本文件与 driver.mjs 一同内嵌到 roami，首次执行按内容 hash 解包到实例缓存。
#
# 驱动全局 Chrome——与 ttmux Web 镜像同一台，自动化能在控制台「浏览器」标签里实时围观。
# 引擎 playwright-core 的 connectOverCDP 复用已开的 Chrome，不下载 Playwright 自带浏览器
# （依赖很轻）。调试端口默认 9222，但后端换过端口就跟着它记录的那个走；要自己拉起 Chrome 时
# 也照 Settings「浏览器」页存的那份配置（无头/有头、窗口、缩放、profile）来，见 _ensure_browser。
#
set -euo pipefail

TTMUX_CHROME_VERSION="0.1.0"
# CLI 自己的运行时目录（内嵌 driver + playwright-core）。注意别给 TTMUX_DATA 赋默认值——
# 它同时是后端数据目录的覆盖变量，赋了默认值 _roam_data() 就再也找不到 ~/.roam。
CHROME_DIR="${ROAMI_DATA:-${ROAM_DATA:-${TTMUX_DATA:-${ROAMI_HOME:-${ROAM_HOME:-${TTMUX_HOME:-${HOME}/.roami}}}}}}/cache/chrome-runtime"

# 颜色/提示
if [ -t 2 ]; then
    _c_blue=$'\033[34m'; _c_red=$'\033[31m'; _c_dim=$'\033[2m'; _c_reset=$'\033[0m'
else
    _c_blue=''; _c_red=''; _c_dim=''; _c_reset=''
fi
_info() { echo -e " ${_c_blue}●${_c_reset} $*" >&2; }
_err()  { echo -e " ${_c_red}✘${_c_reset} $*" >&2; }

# ttmux 后端的数据目录（与 backend 的 dataDir() 同解析）。Settings 页存的 Chrome 配置
# (browser-config.json) 和后端实际在用的 CDP 端口 (browser-cdp-port) 都在这里；不读它，
# CLI 就会按自己那套默认值另开一台 Chrome，Web「浏览器」标签里看不见 CLI 的动作。
_roam_data() {
    local d
    for d in "${ROAMI_DATA:-}" "${ROAM_DATA:-}" "${TTMUX_DATA:-}" "${ROAMI_HOME:-}" "${ROAM_HOME:-}" "${TTMUX_HOME:-}"; do
        if [ -n "$d" ]; then echo "$d"; return 0; fi
    done
    echo "${HOME}/.roami"
}

# USER_CDP：命令行上的 --cdp（driver 只认 `--cdp <地址>` 这种分开写的形式）。探活/拉起必须冲着
# 真正下命令的那个地址：不认它，`chrome --cdp <另一台>` 会去探默认那台、顺手白开一台 Chrome。
# ADOPTED_CDP：本次运行中改用的地址（见 _adopt_existing）。两者必须分开——用「有没有 --cdp」
# 决定要不要把地址传给 driver，就不能拿同一个变量兼职存采纳结果，否则采纳成功等于没传。
USER_CDP=''
ADOPTED_CDP=''
_scan_cdp_arg() {
    local a prev=''
    for a in "$@"; do
        if [ "$prev" = "--cdp" ]; then USER_CDP="$a"; return 0; fi
        prev="$a"
    done
}

# 目标 CDP 地址：命令行 --cdp 最高，其次本次采纳到的实例，再是显式 env，再是后端记录的端口
# （9222 被占时它会自动换端口并记下来），最后才是默认 9222。
_cdp() {
    if [ -n "${USER_CDP:-}" ]; then echo "$USER_CDP"; return 0; fi
    if [ -n "${ADOPTED_CDP:-}" ]; then echo "$ADOPTED_CDP"; return 0; fi
    if [ -n "${TTMUX_CHROME_CDP:-}" ]; then echo "$TTMUX_CHROME_CDP"; return 0; fi
    local f port
    f="$(_roam_data)/browser-cdp-port"
    if [ -r "$f" ]; then
        port="$(tr -dc 0-9 < "$f")"
        if [ -n "$port" ]; then echo "http://127.0.0.1:${port}"; return 0; fi
    fi
    echo "http://127.0.0.1:9222"
}

# 从 CDP 地址里取端口（拉起 Chrome 时要用同一个，写死 9222 会造出「探 A 口、开 B 口」）。
_cdp_port() {
    local p="${1##*:}"
    p="${p%%/*}"
    p="$(printf '%s' "$p" | tr -dc 0-9)"
    if [ -n "$p" ]; then echo "$p"; else echo 9222; fi
}

# 读 Settings 页存的 Chrome 启动配置，按后端同一优先级「存的值 > 环境变量 > 默认」解析成
# CFG_* 变量。语义的权威出处是 backend/browser/{config,browser}.go，改那边这里要跟。
_load_browser_cfg() {
    CFG_HEADLESS=''; CFG_WINDOW=''; CFG_SCALE=''; CFG_PROFILE=''; CFG_BIN=''; CFG_FULLSCREEN=''
    local raw k v
    raw="$(node -e '
const fs = require("fs");
let c = {};
try { c = JSON.parse(fs.readFileSync(process.argv[1], "utf8")); } catch (e) {}
const s = (v) => (typeof v === "string" ? v.trim() : "");
const pick = (stored, env, def) => s(stored) || s(env) || def;
const modes = { auto: "auto", on: "on", off: "off", new: "on", true: "on", "1": "on", false: "off", "0": "off" };
const env = process.env;
const fs0 = c.fullscreen === undefined || c.fullscreen === null;
process.stdout.write([
  "headless=" + (modes[s(c.headless).toLowerCase()] || "auto"),
  "window=" + pick(c.windowSize, env.TTMUX_CHROME_WINDOW, "1920,1080"),
  "scale=" + pick(c.scale, env.TTMUX_CHROME_SCALE, "2"),
  "profile=" + pick(c.profile, env.TTMUX_CHROME_PROFILE, "/tmp/ttmux-chrome"),
  "bin=" + pick(c.bin, env.CHROME_BIN, ""),
  "fullscreen=" + ((fs0 ? env.TTMUX_CHROME_FULLSCREEN !== "0" : !!c.fullscreen) ? "1" : "0"),
].join("\n") + "\n");
' "$(_roam_data)/browser-config.json" 2>/dev/null)" || raw=''
    while IFS='=' read -r k v; do
        case "$k" in
            headless)   CFG_HEADLESS="$v" ;;
            window)     CFG_WINDOW="$v" ;;
            scale)      CFG_SCALE="$v" ;;
            profile)    CFG_PROFILE="$v" ;;
            bin)        CFG_BIN="$v" ;;
            fullscreen) CFG_FULLSCREEN="$v" ;;
        esac
    done <<EOF
$raw
EOF
    : "${CFG_HEADLESS:=auto}"
    : "${CFG_WINDOW:=1920,1080}"
    : "${CFG_SCALE:=2}"
    : "${CFG_PROFILE:=/tmp/ttmux-chrome}"
    : "${CFG_FULLSCREEN:=1}"
}

_is_wsl() {
    if [ -n "${WSL_DISTRO_NAME:-}" ] || [ -n "${WSL_INTEROP:-}" ]; then return 0; fi
    grep -qi microsoft /proc/version 2>/dev/null
}

# 与后端同一判定：on=强制无头，off=强制有头，auto=没显示器/WSL(WSLg 那个 DISPLAY 不算真显示器)才无头。
_headless_wanted() {
    case "$CFG_HEADLESS" in
        on)  return 0 ;;
        off) return 1 ;;
    esac
    [ "$(uname -s 2>/dev/null || echo unknown)" = "Darwin" ] && return 1
    _is_wsl && return 0
    [ -z "${DISPLAY:-}" ]
}

_chrome_bin() {
    if [ -n "${CHROME_BIN:-}" ] && [ -x "$CHROME_BIN" ]; then
        echo "$CHROME_BIN"; return 0
    fi
    if command -v google-chrome >/dev/null 2>&1; then
        command -v google-chrome; return 0
    fi
    if command -v chromium >/dev/null 2>&1; then
        command -v chromium; return 0
    fi
    if command -v chromium-browser >/dev/null 2>&1; then
        command -v chromium-browser; return 0
    fi
    if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
        echo "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; return 0
    fi
    if [ -x "/Applications/Chromium.app/Contents/MacOS/Chromium" ]; then
        echo "/Applications/Chromium.app/Contents/MacOS/Chromium"; return 0
    fi
    return 1
}

_daemon_start() {
    if command -v setsid >/dev/null 2>&1; then
        setsid "$@" </dev/null >/dev/null 2>&1 &
    else
        nohup "$@" </dev/null >/dev/null 2>&1 &
    fi
}

# 写出内嵌 driver.mjs（构建时由 driver.mjs 内联）。引号 heredoc → JS 原样不展开。
# 原子刷新文件，保留正在执行动作的 daemon；新协议动词会让旧 daemon 在动作前拒绝。
_write_driver() {
    mkdir -p "$CHROME_DIR"
    local tmp="${CHROME_DIR}/driver.mjs.$$.tmp" # 带 pid：并发的多条命令共用一个临时名会互相抢，
                                               # 一个 mv 走了、其余全报 cannot stat 然后被 set -e 掀掉
    cat > "$tmp" <<'TTMUX_CHROME_DRIVER_EOF'
@@DRIVER@@
TTMUX_CHROME_DRIVER_EOF
    local receipt_tmp="${CHROME_DIR}/operation-receipts.mjs.$$.tmp"
    cat > "$receipt_tmp" <<'ROAMI_OPERATION_RECEIPTS'
@@OPERATION_RECEIPTS@@
ROAMI_OPERATION_RECEIPTS
    if [ -f "${CHROME_DIR}/operation-receipts.mjs" ] && cmp -s "$receipt_tmp" "${CHROME_DIR}/operation-receipts.mjs"; then
        rm -f "$receipt_tmp"
    else
        mv -f "$receipt_tmp" "${CHROME_DIR}/operation-receipts.mjs"
    fi
    local observation_tmp="${CHROME_DIR}/browser-observation.mjs.$$.tmp"
    cat > "$observation_tmp" <<'ROAMI_BROWSER_OBSERVATION'
@@BROWSER_OBSERVATION@@
ROAMI_BROWSER_OBSERVATION
    if [ -f "${CHROME_DIR}/browser-observation.mjs" ] && cmp -s "$observation_tmp" "${CHROME_DIR}/browser-observation.mjs"; then
        rm -f "$observation_tmp"
    else
        mv -f "$observation_tmp" "${CHROME_DIR}/browser-observation.mjs"
    fi
    if [ -f "${CHROME_DIR}/driver.mjs" ] && cmp -s "$tmp" "${CHROME_DIR}/driver.mjs"; then
        rm -f "$tmp"
        return 0
    fi
    mv -f "$tmp" "${CHROME_DIR}/driver.mjs"
}

# 安装/校验依赖：node + npm + playwright-core
_setup() {
    command -v node >/dev/null 2>&1 || { _err "需要 node（未找到）"; return 1; }
    command -v npm  >/dev/null 2>&1 || { _err "需要 npm（未找到）"; return 1; }
    _write_driver
    if [ ! -d "${CHROME_DIR}/node_modules/playwright-core" ]; then
        _info "安装 playwright-core → ${CHROME_DIR}（首次, 不下载额外浏览器）"
        ( cd "$CHROME_DIR" \
            && { [ -f package.json ] || npm init -y >/dev/null 2>&1; } \
            && npm i --no-audit --no-fund --loglevel=error playwright-core >&2 ) \
            || { _err "playwright-core 安装失败（可重试: chrome setup）"; return 1; }
    fi
    return 0
}

_probe() { curl -fsS -m 2 "${1}/json/version" >/dev/null 2>&1; }

# 找「已经在跑、且用同一个 user-data-dir 的 Chrome 浏览器进程」的调试端口。逐 token 精确比对
# （子串匹配会让 /tmp/x 命中 /tmp/x-headed），并跳过带 --type= 的子进程（renderer 也带着同样的
# profile 和端口参数）。ps 而不是 /proc：macOS 也要能用。
_running_profile_port() {
    ps -eo args= 2>/dev/null | awk -v prof="--user-data-dir=$1" '
        {
            port = ""; hasprof = 0; child = 0
            for (i = 1; i <= NF; i++) {
                if ($i == prof) hasprof = 1
                else if ($i ~ /^--type=/) child = 1
                else if ($i ~ /^--remote-debugging-port=/) { split($i, a, "="); port = a[2] }
            }
            if (hasprof && !child && port != "") { print port; exit }
        }'
}

# 单实例：同 profile 的 Chrome 已经在跑（只是端口不是我们要的那个）→ 认下它。同 user-data-dir
# 的 Chrome 是单例，这时候再拉一个只会把命令行转交给它然后自己退出，端口永远不开。
_adopt_existing() {
    local p; p="$(_running_profile_port "$CFG_PROFILE")"
    [ -n "$p" ] || return 1
    local addr="http://127.0.0.1:${p}"
    [ "$addr" = "$(_cdp)" ] && return 1
    _probe "$addr" || return 1
    _info "已有同 profile 的 Chrome 在 ${p}，用它（不开第二台）"
    ADOPTED_CDP="$addr" # 后面 exec 时会作为 --cdp 传给 driver
    return 0
}

# 确保 CDP 端口上有 Chrome：先探活（后端那台在就直接附着），否则按 Settings 页存的那份
# 配置自起——模式/窗口/缩放/profile/可执行路径全部与后端 ensureChrome 取同一份值，
# 免得「设置里选了有头、CLI 却又开一台无头的」。
_ensure_browser() {
    local base; base="$(_cdp)"
    _probe "$base" && return 0
    _load_browser_cfg
    _adopt_existing && return 0
    # 跨进程串行：并发跑的多条 chrome 命令（agent 一次并行开一串很常见）不该各拉一台。
    # 拿到锁后重新探一遍——等锁期间大概率已经有人拉起来了。拿不到锁就照旧往下走，
    # 宁可多探一次，也不要在这里把命令卡死。
    # 注意别写成 `exec 9>file 2>/dev/null`：exec 不带命令时那个 2>/dev/null 会永久按在整个
    # 脚本的 stderr 上，之后所有报错（含 driver 的）全被吞掉，只剩一个静默的非零退出码。
    local locked=0
    if command -v flock >/dev/null 2>&1; then
        if exec 9>"${CHROME_DIR}/launch.lock"; then
            flock -w 30 9 || true # 等不到锁就自己去探/去起，别把命令卡死在这儿
            locked=1
        fi
    fi
    if [ "$locked" = 1 ] && { _probe "$(_cdp)" || _adopt_existing; }; then
        exec 9>&-
        return 0
    fi
    local rc=0
    _launch_browser || rc=$? # 不用裸调用：set -e 会让失败直接掀掉整个脚本，跳过下面的解锁
    [ "$locked" = 1 ] && exec 9>&-
    return $rc
}

_launch_browser() {
    local base; base="$(_cdp)"
    local chrome_bin
    if [ -n "$CFG_BIN" ] && [ -x "$CFG_BIN" ]; then
        chrome_bin="$CFG_BIN"
    else
        chrome_bin="$(_chrome_bin)" || { _err "${base} 上无 Chrome，且未找到 Chrome/Chromium"; return 1; }
    fi
    local port; port="$(_cdp_port "$base")"
    local args=(--remote-debugging-port="$port" --remote-debugging-address=127.0.0.1
        --remote-allow-origins=* --user-data-dir="$CFG_PROFILE"
        --no-first-run --no-default-browser-check
        # 参数与后端 ensureChrome 逐字一致：这台 Chrome 可能是后端起的、也可能是这里起的，
        # 参数不一样就成了「谁抢到启动谁说话」。自签证书的容忍度由 driver 按 CDP 逐标签打开
        # （见 allowInsecureTLS），不再靠启动开关——那个只在「CLI 抢到启动」时才生效。
        --disable-blink-features=AutomationControlled
        --force-device-scale-factor="$CFG_SCALE")
    local mode=有头
    if _headless_wanted; then
        mode=无头
        args+=(--headless=new --window-size="$CFG_WINDOW")
    elif [ "$CFG_FULLSCREEN" = "1" ]; then
        args+=(--start-fullscreen)
    fi
    _info "拉起 Chrome（${mode}，调试端口 ${port}）..."
    _daemon_start "$chrome_bin" "${args[@]}" about:blank
    # 按总时限等，不按次数：端口上蹲着「只监听不回话」的进程时每次探活都要等满超时，
    # 按次数写就是 50 × 超时（分钟级卡住），而 agent 那头只会觉得 chrome 命令死了。
    local deadline=$((SECONDS + 8))
    while [ "$SECONDS" -lt "$deadline" ]; do
        curl -fsS -m 1 "${base}/json/version" >/dev/null 2>&1 && return 0
        sleep 0.2
    done
    # 同一 user-data-dir 的 Chrome 是单例：profile 被别的实例占着时，新起的这个会把 about:blank
    # 转给它然后自己退出，端口永远不开——错误里点出来，否则只看到「未就绪」无从下手。
    _err "Chrome 调试端口 ${port} 未就绪（若 profile ${CFG_PROFILE} 已被另一台 Chrome 占用：同一 user-data-dir 只能有一个实例，先关掉那台或在设置里换 profile）"
    return 1
}

_help() {
    cat <<'EOF'
roami chrome — 浏览器自动化（Playwright over CDP，驱动 ttmux Web 镜像那台 Chrome）

  roami chrome setup                     安装/更新依赖 (node + playwright-core)
  roami chrome goto <url> [--wait-until load|domcontentloaded|commit]  打开网址
  roami chrome click <选择器>            点击
  roami chrome fill  <选择器> <文本>     填表单（直接设值）
  roami chrome type  <选择器> <文本>     逐字键入
  roami chrome press [选择器] <键>       按键（如 Enter / Control+a）
  roami chrome text  [选择器]            取可见文本（默认 body）
  roami chrome html  [选择器]            取 HTML（默认整页）
  roami chrome attr  <选择器> <属性>     取属性值
  roami chrome eval  "<js>"              页面内执行 JS 并打印返回（JSON）
  roami chrome wait  <选择器>            等待元素出现
  roami chrome screenshot [文件] [--full]   截图（默认 screenshot.png）
  roami chrome pdf   [文件]              导出 PDF（headless）
  roami chrome capabilities              查询驱动能力与浏览器实例身份
  roami chrome observe --target <id> [--screenshot <文件.png>]
  roami chrome tabs                      列出标签页（序号 / 标题 / url）
  roami chrome new   [url]               新开标签页
  roami chrome close                     关闭标签页
  roami chrome record start <文件.mp4>   录制目标标签当前画面（需要系统装有 ffmpeg）
  roami chrome record stop               停止并落盘录制
  roami chrome record status             查看是否在录制
  roami chrome operation-status --operation-id <id> --receipt-root <目录>
  roami chrome operation-cancel --operation-id <id> --receipt-root <目录>

  通用选项: --target <稳定ID> | --tab <序号> | --url <子串>  选目标标签页（默认第一个）
            --no-retry（仅执行一次，未知结果不重放）
            --operation-id <32位ID> --receipt-root <私有目录>（持久化动作回执）
            --expected-browser <实例ID> --expected-scene <观察签名>（动作前验证）
            --timeout <ms>（默认 15000）  --cdp <地址>
  截图选项: --viewport 1280x800  --wait <ms>  --clip x,y,w,h  --fast
            --fresh --goto <url>（临时干净 Chrome 截图）  --quality <1-100>（jpg）
            --mobile（手机视口=iPhone）  --device iphone|iphone-se|pixel|ipad（指定机型）
            默认截图失败时自动降级到 CDP 截图；所有路径受 --timeout 约束
  目标 Chrome: 默认跟着 ttmux 后端那台（读 <数据目录>/browser-cdp-port，缺省 9222）；
            端口上没有 Chrome 时按 Settings「浏览器」页存的配置自起（无头/有头、窗口、
            缩放、profile、可执行路径），与后端拉起的那台参数一致。
  环境变量: TTMUX_CHROME_CDP=http://127.0.0.1:9222（固定目标，优先于上面的记录）
            TTMUX_CHROME_SCALE=2  TTMUX_CHROME_WINDOW=1920,1080（无设置时的兜底）
            ROAMI_HOME / ROAMI_DATA（后端数据目录，默认 ~/.roami）
            TTMUX_CHROME_DAEMON_IDLE=300（常驻 daemon 空闲自杀秒数）
EOF
}

# ── 主入口 ──
sub="${1:-help}"
case "$sub" in
    help|-h|--help) _help; exit 0 ;;
    -v|--version)   echo "chrome v${TTMUX_CHROME_VERSION}"; exit 0 ;;
    setup)          _setup; exit $? ;;
esac
if [ "$sub" = "operation-status" ] || [ "$sub" = "operation-cancel" ]; then
    _write_driver
    exec node "${CHROME_DIR}/driver.mjs" "$@"
fi
_scan_cdp_arg "$@"
fresh_screenshot=0
if [ "$sub" = "screenshot" ] || [ "$sub" = "shot" ]; then
    for arg in "$@"; do
        [ "$arg" = "--fresh" ] && fresh_screenshot=1 && break
    done
fi

# 首次/缺失才跑完整 setup（装依赖）；齐了就走快路径。
if [ ! -f "${CHROME_DIR}/driver.mjs" ] || [ ! -d "${CHROME_DIR}/node_modules/playwright-core" ]; then
    _setup || exit 1
else
    # 根 chrome 是单文件分发；每次执行刷新内嵌 driver，确保升级后的 CLI 立即生效。
    _write_driver
fi
if [ "$fresh_screenshot" -eq 0 ]; then
    _ensure_browser || exit 1
fi
# 目标地址逐条命令显式传下去：常驻 daemon 是先起先得，它进程里的 env 还是当初拉起它那次的，
# 后端换了端口以后只靠 env 会把命令发到已经不在了的那台上。
cdp_arg=()
if [ -z "$USER_CDP" ]; then cdp_arg=(--cdp "$(_cdp)"); fi
exec node "${CHROME_DIR}/driver.mjs" "$@" ${cdp_arg[@]+"${cdp_arg[@]}"}
