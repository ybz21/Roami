#!/usr/bin/env bash
#
# 验证 swarm 广场 @mention / listen 增量监听
# 用法: bash tests/test_swarm_listen.sh
#

set -euo pipefail

ROAMI_BIN="${ROAMI_BIN:-roami}"
session_cli() { "$ROAMI_BIN" session "$@"; }
TTMUX=session_cli
TMP="$(mktemp -d /tmp/ttmux-swarm-listen.XXXXXX)"
for storage_prefix in ROAMI ROAM TTMUX; do
  for storage_suffix in HOME DATA CONFIG DATABASE_DIR BACKUP_DIR; do
    unset "${storage_prefix}_${storage_suffix}"
  done
done
export TTMUX_HOME="${TMP}/home"
export TTMUX_DATA="${TMP}/data"
FAKE_BIN="${TMP}/bin"
FAKE_TMUX_LOG="${TMP}/fake-tmux.log"
mkdir -p "$FAKE_BIN"
cat > "${FAKE_BIN}/tmux" <<'FAKE_TMUX'
#!/usr/bin/env bash
echo "$*" >> "${FAKE_TMUX_LOG:?}"
case "${1:-}" in
  load-buffer) cat >> "${FAKE_TMUX_LOG:?}"; exit 0 ;;
  display-message)
    case "$*" in *pane_dead*) echo 0; exit 0 ;; *) exit 1 ;; esac
    ;;
  capture-pane)
    case "$*" in
      *listen-case-oldlead*) echo "❯"; exit 0 ;;
      *listen-case-oldmember*) echo "Press enter"; exit 0 ;;
      *listen-case-oldrun*) echo "✻ Puzzling…"; exit 0 ;;
      *) exit 0 ;;
    esac
    ;;
  has-session)
    case "$*" in *"cc-listen-case"*|*"listen-case-oldlead"*|*"listen-case-oldmember"*|*"listen-case-oldrun"*) exit 0 ;; *) exit 1 ;; esac
    ;;
  list-sessions) exit 0 ;;
  send-keys) exit 0 ;;
  *) exit 0 ;;
esac
FAKE_TMUX
chmod +x "${FAKE_BIN}/tmux"
export FAKE_TMUX_LOG
export PATH="${FAKE_BIN}:${PATH}"

PASS=0
FAIL=0

bold=$'\033[1m'
green=$'\033[32m'
red=$'\033[31m'
dim=$'\033[2m'
reset=$'\033[0m'

pass() { echo -e "  ${green}✔${reset} $1"; ((PASS++)) || true; }
fail() { echo -e "  ${red}✘${reset} $1"; ((FAIL++)) || true; }

cleanup() {
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

assert_not_contains() {
    local haystack="$1" needle="$2" label="$3"
    if grep -Fq "$needle" <<< "$haystack"; then
        fail "$label"
        echo "---- output ----"
        echo "$haystack"
        echo "----------------"
    else
        pass "$label"
    fi
}

message_section() {
    sed '/状态摘要/,$d'
}

echo ""
echo -e "${bold}swarm listen / @mention 测试${reset}"
echo -e "${dim}$(printf '─%.0s' {1..44})${reset}"
echo ""

echo -e "${bold}[准备]${reset}"
"$TTMUX" swarm new listen-case --goal "监听 case" --no-master >/dev/null
pass "创建蜂群"

swarm_id=$(sqlite3 "${TTMUX_DATA}/database/meta.db" "SELECT id FROM swarms WHERE name='listen-case';")
sqlite3 "${TTMUX_DATA}/database/meta.db" "INSERT INTO swarm_members(swarm_id,name,type,task,role,pending,done) VALUES('${swarm_id}','oldlead','agent','旧 leader','leader',0,0),('${swarm_id}','oldmember','agent','旧 member','member',0,0),('${swarm_id}','oldrun','agent','运行中 member','member',0,0);"
status_json=$("$TTMUX" swarm status listen-case --json)
assert_contains "$status_json" '"role":"leader"' "leader 角色可读取"
assert_contains "$status_json" '"role":"member"' "member 角色可读取"
assert_contains "$status_json" '"status":"idle"' "空闲 agent 状态显示为 idle"
assert_contains "$status_json" '"status":"waiting"' "待确认 agent 状态显示为 waiting"
assert_contains "$status_json" '"status":"running"' "Claude 活动状态显示为 running"

card=$("$TTMUX" swarm task add listen-case "前端返工" --assignee web 2>/dev/null)
[[ "$card" == "t1" ]] && pass "创建并派卡 t1 → web" || fail "创建卡片: got '${card}'"

"$TTMUX" swarm say listen-case --as human --to leader --kind ask "补移动端验收" >/dev/null
"$TTMUX" swarm say listen-case --as leader --to web --kind decide "#${card} 补空状态" >/dev/null
"$TTMUX" swarm say listen-case --as api --kind note "普通进度" >/dev/null
pass "写入 leader/web/普通三类广场消息"
status_json=$("$TTMUX" swarm status listen-case --json)
leader_status=$(python3 -c 'import json,sys; print(next(m["status"] for m in json.load(sys.stdin)["members"] if m["name"]=="oldlead"))' <<< "$status_json")
assert_contains "$leader_status" 'running' "发给 leader 后短期显示 running"
echo ""

echo -e "${bold}[@mention 写入]${reset}"
feed=$("$TTMUX" swarm feed listen-case)
assert_contains "$feed" "@leader 补移动端验收" "--to leader 自动写入 @leader"
assert_contains "$feed" "@web #t1 补空状态" "--to web 自动写入 @web"
assert_contains "$feed" "普通进度" "普通消息仍保留"
echo ""

echo -e "${bold}[leader listen]${reset}"
master_out=$("$TTMUX" swarm listen listen-case --as leader --once --no-advance)
master_msgs=$(printf '%s\n' "$master_out" | message_section)
assert_contains "$master_msgs" "[HIGH]" "leader 标注 human/@leader 为 HIGH"
assert_contains "$master_msgs" "@leader 补移动端验收" "leader 看到 human 指令"
assert_contains "$master_msgs" "@web #t1 补空状态" "leader 看到全量广场消息"
echo ""

echo -e "${bold}[worker mentions listen]${reset}"
web_out=$("$TTMUX" swarm listen listen-case --as web --mentions --once --no-advance)
web_msgs=$(printf '%s\n' "$web_out" | message_section)
assert_contains "$web_msgs" "@web #t1 补空状态" "web worker 收到 @web 消息"
assert_not_contains "$web_msgs" "@leader 补移动端验收" "web member 不收 @leader 消息"
assert_not_contains "$web_msgs" "普通进度" "web worker 不收无关 note"
echo ""

echo -e "${bold}[游标推进]${reset}"
"$TTMUX" swarm listen listen-case --as leader --once >/dev/null
empty_out=$("$TTMUX" swarm listen listen-case --as leader --once)
assert_contains "$empty_out" "(没有新广场消息)" "游标推进后不重复吐旧消息"

"$TTMUX" swarm say listen-case --as human --to leader --kind ask "第二条 human 指令" >/dev/null
next_out=$("$TTMUX" swarm listen listen-case --as leader --once)
next_msgs=$(printf '%s\n' "$next_out" | message_section)
assert_contains "$next_msgs" "@leader 第二条 human 指令" "游标后新消息仍可读取"
assert_not_contains "$next_msgs" "@leader 补移动端验收" "新一轮不回放旧 human 消息"
status_json=$("$TTMUX" swarm status listen-case --json)
assert_contains "$status_json" '"leader_last_post":4' "状态 JSON 暴露 leader 已处理游标"
echo ""

echo -e "${bold}[leader 会话通知]${reset}"
sqlite3 "${TTMUX_DATA}/database/meta.db" "UPDATE swarms SET supervisor='cc-listen-case' WHERE name='listen-case';"
: > "$FAKE_TMUX_LOG"
"$TTMUX" swarm say listen-case --as human --to leader --kind ask "触发 leader 通知" >/dev/null
notify_log=$(<"$FAKE_TMUX_LOG")
assert_contains "$notify_log" "has-session -t =cc-listen-case" "检查 supervisor 会话是否存在"
assert_contains "$notify_log" "paste-buffer -p -d -b roami-prompt-" "human 消息粘贴给 leader"
assert_contains "$notify_log" "send-keys -t =cc-listen-case: Enter" "human 消息强制提交给 leader"
assert_contains "$notify_log" "roami session swarm listen listen-case --as leader --once" "通知内容要求 leader 执行 listen"
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
