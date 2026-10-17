#!/usr/bin/env bash
# Roami 自检：能用命令验的那一半。
#
#   scripts/dev/selftest/roami-selftest.sh [--url https://localhost:13579] [--remote]
#
# 每条打一行 PASS/FAIL/WARN，末尾给汇总；有 FAIL 就 exit 1（定时任务据此判断要不要报警）。
# 看得见的那一半（界面、手机档、镜像画面）在
# docs/development/roami-selftest-checklist.md 里，由 Agent 用浏览器跑。
#
# 口令从 ~/.roami/config.yaml 读，绝不写进脚本，也绝不打印。
set -uo pipefail

URL="${ROAMI_URL:-https://localhost:13579}"
REMOTE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --remote) REMOTE=1; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

PASS=0; FAIL=0; WARN=0
ok()   { printf '  PASS  %-30s %s\n' "$1" "${2:-}"; PASS=$((PASS+1)); }
bad()  { printf '  FAIL  %-30s %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }
warn() { printf '  WARN  %-30s %s\n' "$1" "${2:-}"; WARN=$((WARN+1)); }
section() { printf '\n== %s ==\n' "$1"; }

JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
C=(curl -sk --max-time 20 -b "$JAR" -c "$JAR")

HERE="$(cd "$(dirname "$0")" && pwd)"
# 按点分路径取值，见 jval.py（单独一个文件：内联 python 和管道抢同一个 stdin）
jval() { python3 "$HERE/jval.py" "${1:-}" 2>/dev/null; }

# GET 一个端点：验它是 JSON，再按路径取一个数报出来
check_json() {
  local name="$1" path="$2" pick="${3:-}" unit="${4:-}" body got
  body=$("${C[@]}" "$URL$path") || { bad "$name" "请求失败"; return; }
  if ! printf '%s' "$body" | python3 -c 'import sys,json;json.load(sys.stdin)' 2>/dev/null; then
    bad "$name" "不是合法 JSON：$(printf '%s' "$body" | tr -d '\n' | head -c 60)"
    return
  fi
  if [ -z "$pick" ] && [ -z "$unit" ]; then ok "$name"; return; fi
  got=$(printf '%s' "$body" | jval "$pick")
  [ -n "$got" ] && ok "$name" "$got$unit" || bad "$name" "取不到 $pick"
}

section "服务"
if ver=$("${C[@]}" "$URL/api/version"); then
  v=$(printf '%s' "$ver" | jval "version")
  case "$v" in
    "") bad "/api/version" "解析不出版本：$(printf '%s' "$ver" | head -c 60)" ;;
    vdev|*dirty*) warn "/api/version" "$v（手动 go build 丢了 ldflags，或工作区有改动）" ;;
    *) ok "/api/version" "$v" ;;
  esac
else
  bad "/api/version" "连不上 $URL"
fi

if [ "$URL" = "${ROAMI_URL:-https://localhost:13579}" ] && command -v systemctl >/dev/null; then
  systemctl --user is-active --quiet roami.service 2>/dev/null \
    && ok "roami.service" "active" \
    || warn "roami.service" "不是 systemd 起的（前台跑也算正常）"
fi

section "登录"
CONF="${ROAMI_HOME:-$HOME/.roami}/config.yaml"
pw=$(sed -n 's/^[[:space:]]*password:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' "$CONF" 2>/dev/null | head -1)
if [ -z "$pw" ]; then
  bad "读口令" "$CONF 里没找到 web.password"
else
  code=$("${C[@]}" -o /dev/null -w '%{http_code}' -X POST "$URL/api/login" \
    -H 'Content-Type: application/json' \
    --data-binary "$(python3 -c 'import json,sys;print(json.dumps({"password":sys.argv[1]}))' "$pw")")
  [ "$code" = "200" ] && ok "POST /api/login" "cookie 已拿到" || bad "POST /api/login" "HTTP $code"
fi

section "核心接口"
check_json "GET /api/sessions"      "/api/sessions"       ""         " 个会话"
check_json "GET /api/projects"      "/api/projects"       "projects" " 个项目"
check_json "GET /api/plugins"       "/api/plugins"        ""         " 个插件"
check_json "GET /api/preferences"   "/api/preferences"
check_json "GET /api/browser/config" "/api/browser/config"

section "插件（顺带守住「日志混进 JSON」那条回归）"
run_plugin() {
  local name="$1" id="$2" cmd="$3" pick="$4" unit="${5:-}" body got
  body=$("${C[@]}" -X POST "$URL/api/plugins/$id/run" -H 'Content-Type: application/json' \
    --data-binary "{\"command\":\"$cmd\",\"args\":{}}") || { bad "$name" "请求失败"; return; }
  got=$(printf '%s' "$body" | jval "$pick")
  [ -n "$got" ] && ok "$name" "$got$unit" \
    || bad "$name" "响应不可用：$(printf '%s' "$body" | tr -d '\n' | head -c 70)"
}
run_plugin "host-monitor.stats" "roam.host-monitor" "host-monitor.stats" "cpu.usagePercent" "% CPU"
run_plugin "cron.list"          "roam.cron"         "cron.list"          "count"            " 条定时任务"

section "tmux 底座"
if tmux ls >/dev/null 2>&1; then
  ok "tmux server" "$(tmux ls 2>/dev/null | wc -l) 个会话"
else
  bad "tmux server" "连不上（会话全在这上面）"
fi
roami plugin status --json 2>/dev/null | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("daemon") else 1)' \
  && ok "plugind 守护进程" "在" \
  || bad "plugind 守护进程" "不在——插件的定时/常驻能力全停摆"
# 到点触发靠外面按分钟叫一次 cron.tick（插件宿主没有内置调度器）。这一条不在，
# 所有定时任务都只是躺在库里、永远不会跑——包括这份自检自己。
if systemctl --user is-active --quiet roami-cron-tick.timer 2>/dev/null; then
  ok "定时任务巡检" "roami-cron-tick.timer active"
elif pgrep -f "cron[.]serve" >/dev/null 2>&1; then
  ok "定时任务巡检" "cron.serve 常驻中"
else
  bad "定时任务巡检" "没人叫 cron.tick —— 定时任务一条都不会触发（装 scripts/deploy/systemd/）"
fi

if out=$(roami session ls --json 2>/dev/null) && printf '%s' "$out" | python3 -c 'import sys,json;json.load(sys.stdin)' 2>/dev/null; then
  ok "roami session ls --json"
else
  bad "roami session ls --json" "CLI 台账读不出来"
fi

section "前端产物"
asset=$("${C[@]}" "$URL/" | grep -o '/assets/[A-Za-z0-9._-]*\.js' | head -1)
if [ -z "$asset" ]; then
  bad "首页 HTML" "没引到 /assets/*.js（dist 没构建，或 -web 指错了目录）"
else
  code=$("${C[@]}" -o /dev/null -w '%{http_code}' "$URL$asset")
  [ "$code" = "200" ] && ok "首屏资源" "$asset" || bad "首屏资源" "$asset → HTTP $code"
fi

section "容量"
stats=$("${C[@]}" -X POST "$URL/api/plugins/roam.host-monitor/run" -H 'Content-Type: application/json' \
  --data-binary '{"command":"host-monitor.stats","args":{}}')
disk=$(printf '%s' "$stats" | jval "disks.0.usagePercent")
used=$(printf '%s' "$stats" | jval "memory.used")
total=$(printf '%s' "$stats" | jval "memory.total")
[ -n "$disk" ] && { [ "${disk%.*}" -lt 90 ] && ok "磁盘" "${disk%.*}%" || warn "磁盘" "${disk%.*}%（>90% 该清了）"; }
if [ -n "$used" ] && [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then
  mem=$((used * 100 / total))
  [ "$mem" -lt 90 ] && ok "内存" "$mem%" || warn "内存" "$mem%（多半是某个 agent 涨上去了，见 memguard）"
fi

if [ "$REMOTE" = "1" ]; then
  section "另外两台"
  lv=$("${C[@]}" "$URL/api/version" | jval "version")
  for hp in jetson:13579 aliyun:13570; do
    h=${hp%%:*}; p=${hp##*:}
    rv=$(timeout 30 ssh -o BatchMode=yes -o ConnectTimeout=10 "$h" "curl -sk --max-time 10 https://localhost:$p/api/version" 2>/dev/null | jval "version")
    if [ -z "$rv" ]; then bad "$h" "连不上或没起来"
    elif [ "$rv" = "$lv" ]; then ok "$h" "$rv"
    else warn "$h" "$rv（本机 $lv，版本不一致）"; fi
  done
fi

printf '\n== 汇总 ==\n  %d 通过 · %d 失败 · %d 警告\n' "$PASS" "$FAIL" "$WARN"
[ "$FAIL" -eq 0 ]
