#!/usr/bin/env bash
#
# 验证 swarm 持续监听 loop + 看板协作能力
# 用法: bash tests/test_swarm_loop_board.sh
#

set -euo pipefail

ROAMI_BIN="${ROAMI_BIN:-roami}"
session_cli() { "$ROAMI_BIN" session "$@"; }
TTMUX=session_cli
TMP="$(mktemp -d /tmp/ttmux-swarm-loop-board.XXXXXX)"
for storage_prefix in ROAMI ROAM TTMUX; do
  for storage_suffix in HOME DATA CONFIG DATABASE_DIR BACKUP_DIR; do
    unset "${storage_prefix}_${storage_suffix}"
  done
done
export TTMUX_HOME="${TMP}/home"
export TTMUX_DATA="${TMP}/data"

PASS=0
FAIL=0
LISTEN_PID=""

bold=$'\033[1m'
green=$'\033[32m'
red=$'\033[31m'
dim=$'\033[2m'
reset=$'\033[0m'

pass() { echo -e "  ${green}✔${reset} $1"; ((PASS++)) || true; }
fail() { echo -e "  ${red}✘${reset} $1"; ((FAIL++)) || true; }

cleanup() {
    [[ -n "${LISTEN_PID:-}" ]] && kill "$LISTEN_PID" 2>/dev/null || true
    rm -rf "$TMP"
}
trap cleanup EXIT

assert_contains() {
    local haystack="$1" needle="$2" label="$3"
    if grep -Fq "$needle" <<< "$haystack"; then
        pass "$label"
    else
        fail "$label"
        echo "---- output ----"
        echo "$haystack"
        echo "----------------"
    fi
}

wait_for_file_text() {
    local file="$1" needle="$2" timeout="${3:-8}"
    local start now
    start=$(date +%s)
    while true; do
        if [[ -f "$file" ]] && grep -Fq "$needle" "$file"; then
            return 0
        fi
        now=$(date +%s)
        (( now - start >= timeout )) && return 1
        sleep 0.2
    done
}

message_section() {
    sed '/状态摘要/,$d'
}

echo ""
echo -e "${bold}swarm loop + board case${reset}"
echo -e "${dim}$(printf '─%.0s' {1..44})${reset}"
echo ""

SWARM="loop-board-case"

echo -e "${bold}[准备新 swarm]${reset}"
"$TTMUX" swarm new "$SWARM" --goal "验证广场持续监听和看板协作" --no-master >/dev/null
pass "创建 ${SWARM}"

card_web=$("$TTMUX" swarm task add "$SWARM" "前端补回复 UI" --assignee web 2>/dev/null)
card_api=$("$TTMUX" swarm task add "$SWARM" "后端确认 re 字段透传" --assignee api 2>/dev/null)
[[ "$card_web" == "t1" && "$card_api" == "t2" ]] && pass "创建两张看板卡" || fail "创建卡片: web=${card_web} api=${card_api}"
echo ""

echo -e "${bold}[看板流转]${reset}"
board=$("$TTMUX" swarm board "$SWARM")
assert_contains "$board" "t1" "看板显示 t1"
assert_contains "$board" "→ web" "t1 派给 web"
assert_contains "$board" "t2" "看板显示 t2"
assert_contains "$board" "→ api" "t2 派给 api"

"$TTMUX" swarm task move "$SWARM" "$card_web" doing >/dev/null
board=$("$TTMUX" swarm board "$SWARM")
assert_contains "$board" "doing" "看板有 doing 列"
assert_contains "$board" "前端补回复 UI" "t1 进入看板流转视图"

"$TTMUX" swarm task move "$SWARM" "$card_web" review >/dev/null
"$TTMUX" swarm task done "$SWARM" "$card_web" >/dev/null
board_json=$("$TTMUX" swarm board "$SWARM" --json)
assert_contains "$board_json" '"id":"t1"' "JSON 看板包含 t1"
assert_contains "$board_json" '"col":"done"' "t1 已流转到 done"
echo ""

echo -e "${bold}[持续监听 loop]${reset}"
listen_out="${TMP}/listen.out"
"$TTMUX" swarm listen "$SWARM" --as leader --interval 1 --no-advance > "$listen_out" 2>&1 &
LISTEN_PID=$!
sleep 0.5

"$TTMUX" swarm say "$SWARM" --as human --to leader --kind ask "loop 第一条 human 指令" >/dev/null
if wait_for_file_text "$listen_out" "loop 第一条 human 指令" 8; then
    pass "持续 listen 捕获第一条新消息"
else
    fail "持续 listen 未捕获第一条新消息"
fi

"$TTMUX" swarm say "$SWARM" --as human --to leader --kind ask "loop 第二条 human 指令" >/dev/null
if wait_for_file_text "$listen_out" "loop 第二条 human 指令" 8; then
    pass "持续 listen 捕获第二条新消息"
else
    fail "持续 listen 未捕获第二条新消息"
fi

if kill -0 "$LISTEN_PID" 2>/dev/null; then
    pass "listen 进程持续存活"
else
    fail "listen 进程提前退出"
fi
kill "$LISTEN_PID" 2>/dev/null || true
LISTEN_PID=""
echo ""

echo -e "${bold}[看板 + @/# 路由]${reset}"
"$TTMUX" swarm say "$SWARM" --as leader --to web --kind decide "#${card_web} 请确认回复按钮样式" >/dev/null
web_out=$("$TTMUX" swarm listen "$SWARM" --as web --mentions --once --no-advance)
web_msgs=$(printf '%s\n' "$web_out" | message_section)
assert_contains "$web_msgs" "@web #${card_web} 请确认回复按钮样式" "web worker 收到 @web + #卡片消息"

"$TTMUX" swarm say "$SWARM" --as leader --kind decide "#${card_api} 后端 re 字段不用改" >/dev/null
api_out=$("$TTMUX" swarm listen "$SWARM" --as api --mentions --once --no-advance)
api_msgs=$(printf '%s\n' "$api_out" | message_section)
assert_contains "$api_msgs" "#${card_api} 后端 re 字段不用改" "api worker 按负责卡片收到 #t2 消息"
echo ""

echo -e "${dim}$(printf '─%.0s' {1..44})${reset}"
total=$((PASS + FAIL))
if [[ $FAIL -eq 0 ]]; then
    echo -e "${green}${bold}全部通过${reset} ${dim}(${total}/${total})${reset}"
else
    echo -e "${red}${bold}${FAIL} 个失败${reset} ${dim}(${PASS}/${total} 通过)${reset}"
fi
echo ""

exit "$FAIL"
