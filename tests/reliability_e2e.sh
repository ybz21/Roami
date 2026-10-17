#!/usr/bin/env bash
# 可靠性 e2e：会话内存护栏（R1）+ 会话懒恢复（R2）
#
#   bash tests/reliability_e2e.sh            全跑
#   bash tests/reliability_e2e.sh guard      只跑内存护栏
#   bash tests/reliability_e2e.sh revive     只跑懒恢复
#   bash tests/reliability_e2e.sh ui         只跑浏览器那几条（需要 chrome CLI + 服务在跑）
#
# 为什么要有它：这两块的坑几乎全在「跨进程 / 跨内核 / 跨浏览器」的接缝上——
# systemctl 会静默成功、cgroup 目录随会话消失、tree 接口和平铺接口是两份实现、
# 列表看不出休眠态。单测一个都拦不住，只有真起会话、真读 cgroup、真点页面才照得出来。
#
# 用例编号与 docs/design/reliability/*.html 的验收清单对应。
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PASS=0; FAIL=0; SKIP=0
ok()   { printf '  \033[32m✔\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$1"; [ $# -gt 1 ] && printf '      %s\n' "$2"; FAIL=$((FAIL+1)); }
skip() { printf '  \033[33m—\033[0m %s (%s)\n' "$1" "${2:-跳过}"; SKIP=$((SKIP+1)); }
sect() { printf '\n\033[1m%s\033[0m\n' "$1"; }

ROAMI_BIN="${ROAMI_BIN:-roami}"
session_cli() { "$ROAMI_BIN" session "$@"; }
TTMUX=session_cli
command -v "$ROAMI_BIN" >/dev/null || { echo "✘ 找不到 roami"; exit 1; }

# 本次跑出来的会话都打这个前缀，收尾一并清掉，绝不碰用户自己的会话。
TEST_DATABASE_PATH=$("$ROAMI_BIN" db status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')
[ -f "$TEST_DATABASE_PATH" ] || { echo "数据库尚未初始化"; exit 1; }
export TEST_DATABASE_PATH
TAG="e2e-rel-$$"
cleanup() {
  tmux ls -F '#{session_name}	#{@roam_name}' 2>/dev/null | while IFS=$'\t' read -r s l; do
    case "$l" in "$TAG"*) tmux kill-session -t "=$s" 2>/dev/null ;; esac
  done
}
trap cleanup EXIT

# make_dormant <会话id> —— 把它伪装成「上一代 server 带走的」。
#
# 不能真去重启机器，但 died_reason='host-restart' + 对不上的 epoch 就是那个状态。
# died_at 必须写成 **RFC3339 本地时区**，和产品写进去的一模一样：Dormant() 用
# `ORDER BY died_at DESC LIMIT 1` 挑「最新一代」，那是**字符串**比较，而 sqlite 的
# datetime('now') 给的是 "2026-08-23 10:42:15"（空格分隔、UTC）——空格(0x20) < 'T'(0x54)，
# 伪造的行会排在真实那批后面，于是这条测试数据自己把自己排除了。
make_dormant() {
  local sid="$1" epoch
  epoch=$(tmux display-message -p '#{pid}' 2>/dev/null)
  tmux kill-session -t "=$sid" 2>/dev/null
  # 等 tmux 真的把会话收走再改台账。**不等就会被覆盖**：后端每几秒轮询一次
  # /sessions，Reconcile 见「死行上又冒出同名会话」会把它复活成 live + 当前 epoch，
  # 我们刚写的 host-restart 就没了（实测 died_reason 变回 killed）。
  local n=0
  until ! tmux has-session -t "=$sid" 2>/dev/null || [ $n -ge 10 ]; do sleep 0.3; n=$((n+1)); done
  python3 - "$sid" "$epoch" <<'PYEOF'
import sqlite3,sys,os,datetime,time
sid,epoch=sys.argv[1],sys.argv[2]
db=os.environ['TEST_DATABASE_PATH']
want=epoch+'-old'
# 写完回读确认，不对就重来——和产品里 memguard.Apply 必须回读 memory.max 同一个道理：
# 有别的写者在并发改这张表，"命令返回 0" 证明不了状态。
for attempt in range(5):
    c=sqlite3.connect(db, timeout=5)
    now=datetime.datetime.now().astimezone().isoformat()
    c.execute("update sessions set status='dead', died_reason='host-restart', tmux_epoch=?, "
              "died_at=?, restored_from=NULL where id=?", (want, now, sid))
    c.commit()
    got=list(c.execute("select status,died_reason,tmux_epoch from sessions where id=?", (sid,)))
    c.close()
    if got and got[0]==('dead','host-restart',want):
        break
    time.sleep(0.6)
else:
    print(f"make_dormant: {sid} 没能稳定在 host-restart（最后读到 {got}）", file=sys.stderr)
PYEOF
}

# mk <名字后缀> [额度] —— 建一个带标记的会话，回显会话 id
mk() {
  local suffix="$1" max="${2:-}"
  local out
  if [ -n "$max" ]; then
    out=$(ROAM_SESSION_MEM_MAX="$max" "$TTMUX" new "$TAG-$suffix" --detach --json 2>/dev/null)
  else
    out=$("$TTMUX" new "$TAG-$suffix" --detach --json 2>/dev/null)
  fi
  echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("session",""))' 2>/dev/null
}
pane_pid() { tmux list-panes -s -t "=$1" -F '#{pane_pid}' 2>/dev/null | head -1; }
cg_dir()   { local p; p=$(pane_pid "$1"); [ -n "$p" ] && echo "/sys/fs/cgroup$(cut -d: -f3 < /proc/"$p"/cgroup 2>/dev/null)"; }
db()       { python3 -c "
import sqlite3,sys,os
c=sqlite3.connect(os.environ['TEST_DATABASE_PATH'])
r=list(c.execute(sys.argv[1], sys.argv[2:]))
print(r[0][0] if r and r[0][0] is not None else '')" "$@"; }

guard_supported() {
  [ -f /sys/fs/cgroup/cgroup.controllers ] \
    && command -v systemctl >/dev/null \
    && grep -q memory "/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers" 2>/dev/null
}

# ── R1 内存护栏 ────────────────────────────────────────────────────────
run_guard() {
  sect "R1 会话内存护栏"
  if ! guard_supported; then
    skip "整组" "本机不支持（cgroup v1 / 无 systemd / 控制器未委派）—— 护栏应静默降级"
    local s; s=$(mk g0)
    [ -n "$s" ] && ok "G0 护栏装不上时照样能建会话（降级不阻断）" || bad "G0 建会话失败"
    return
  fi

  # G1 建会话即生效。**连建 5 个**：set-property 对还没注册完的 transient scope
  # 会静默成功（exit 0 但属性没落上），一次成功说明不了问题，间歇性才是它的本相。
  local hit=0 i s d
  for i in 1 2 3 4 5; do
    s=$(mk "g1-$i" 4G); d=$(cg_dir "$s")
    [ -n "$d" ] && [ "$(cat "$d/memory.max" 2>/dev/null)" = "4294967296" ] && hit=$((hit+1))
  done
  [ "$hit" = 5 ] && ok "G1 连建 5 个会话，上限 5/5 生效" || bad "G1 上限只在 $hit/5 次生效" "set-property 静默成功的竞态回来了：Apply 必须回读 memory.max 确认"

  # G2 软限严格低于硬顶。6G 是特意选的：它的 75% 不整除，
  # 按单位做整数除法会截成 4G——8G 正好整除，看不出这个 bug。
  s=$(mk g2 6G); d=$(cg_dir "$s")
  local mx hi
  mx=$(cat "$d/memory.max" 2>/dev/null); hi=$(cat "$d/memory.high" 2>/dev/null)
  if [ "$mx" = "6442450944" ] && [ "$hi" = "4831838208" ]; then
    ok "G2 6G 的软限是 4.5G（不整除额度不被截断）"
  else
    bad "G2 max=$mx high=$hi" "期望 max=6442450944 high=4831838208"
  fi

  # G3 撞顶只杀失控进程，会话本身活着。这是整个护栏的立身之本：
  # 它要是把会话也带走，就和 global_oom 没区别了。
  s=$(mk g3 300M); d=$(cg_dir "$s")
  systemctl --user set-property "$(basename "$d")" MemoryHigh=infinity MemorySwapMax=0 2>/dev/null
  tmux send-keys -t "=$s:" "python3 -c 'a=[]
while 1: a.append(bytearray(30*1024*1024))'" C-m 2>/dev/null
  local n=0
  until [ "$(awk '/^oom_kill /{print $2}' "$d/memory.events" 2>/dev/null)" != "0" ] || [ $n -ge 25 ]; do sleep 1; n=$((n+1)); done
  local ooms group
  ooms=$(awk '/^oom_kill /{print $2}' "$d/memory.events" 2>/dev/null)
  group=$(awk '/^oom_group_kill /{print $2}' "$d/memory.events" 2>/dev/null)
  if [ "${ooms:-0}" -ge 1 ] && tmux has-session -t "=$s" 2>/dev/null; then
    ok "G3 撞顶杀掉失控进程（oom_kill=$ooms group_kill=$group），会话存活"
  else
    bad "G3 oom_kill=$ooms 会话存活=$(tmux has-session -t "=$s" 2>/dev/null && echo 是 || echo 否)"
  fi

  # G4 撞顶要留下证据。cgroup 目录随会话一起消失，所以计数必须趁活着时落库——
  # 「等发现它没了再去读 memory.events」是读不到的。
  "$TTMUX" ls >/dev/null 2>&1
  local rec_ooms rec_peak
  rec_ooms=$(db "select oom_kills from sessions where id=?" "$s")
  rec_peak=$(db "select peak_rss from sessions where id=?" "$s")
  [ "${rec_ooms:-0}" -ge 1 ] && ok "G4 oom 次数落台账（oom_kills=$rec_ooms peak=$((${rec_peak:-0}/1024/1024))MB）" \
    || bad "G4 台账没记下 oom（oom_kills=$rec_ooms）" "cgroup 目录会随会话消失，必须在采集时就落库"

  # G5 会话结束后 died_reason 记成 oom 而不是 killed
  tmux kill-session -t "=$s" 2>/dev/null; "$TTMUX" ls >/dev/null 2>&1
  local reason; reason=$(db "select died_reason from sessions where id=?" "$s")
  [ "$reason" = "oom" ] && ok "G5 died_reason=oom（不是笼统的 killed）" || bad "G5 died_reason=$reason" "期望 oom"

  # G7 内存条报的必须是**真占用**（anon），不是 memory.current。
  #
  # current 把 page cache 一起算进来，而那是内核为加速留的、内存紧张时自己就会回收的。
  # 实测一个跑完两次交叉编译的会话 current=4.37G，其中 anon 只有 0.75G——
  # 拿 current 画条，用户看到 4.4G 会以为漏了；看门狗按它算百分比更会凭空报警。
  # 这条特意**先把缓存撑起来**再比，否则两个数字本来就一样，测了也白测。
  s=$(mk g7)
  d=$(cg_dir "$s")
  # 撑 page cache：**写**一个新文件，别去读老文件。
  # page cache 是全局共享的，只有**首次读入**才 charge 给某个 cgroup——
  # 反复跑测试时那些文件早就在缓存里了，再读一遍这个 cgroup 一分钱不涨
  # （实测就是这么一直 skip 的）。而写入产生的脏页必然算在写的人头上。
  local tmpf="/tmp/roami-e2e-cache-$$.bin"
  tmux send-keys -t "=$s:" "dd if=/dev/zero of=$tmpf bs=1M count=300 2>/dev/null; cat $tmpf >/dev/null" C-m 2>/dev/null
  local w=0
  until [ "$(cat "$d/memory.current" 2>/dev/null || echo 0)" -gt $((250*1024*1024)) ] || [ $w -ge 20 ]; do sleep 1; w=$((w+1)); done
  sleep 1
  local anon cur shown
  anon=$(awk '/^anon /{print $2}' "$d/memory.stat" 2>/dev/null)
  cur=$(cat "$d/memory.current" 2>/dev/null)
  "$TTMUX" ls >/dev/null 2>&1
  shown=$("$TTMUX" ls --json 2>/dev/null | python3 -c "
import json,sys
for r in json.load(sys.stdin):
    if r['name']=='$s': print(r.get('mem',{}).get('cur',0)); break
else: print(0)")
  # 要求 current 比 anon 多出至少 100MB 才算「撑起来了」。
  # 两个都接近 0 时去比大小毫无意义——那种情况下测试恒过或恒挂，都不说明问题。
  if [ $(( ${cur:-0} - ${anon:-0} )) -lt $((100*1024*1024)) ]; then
    skip "G7 内存条报真占用" "这一轮没能撑出 page cache 差异（anon=$((${anon:-0}/1024/1024))M current=$((${cur:-0}/1024/1024))M）"
  elif python3 -c "import sys; sys.exit(0 if abs($shown-$anon) < 64*1024*1024 and $shown < $cur*0.7 else 1)"; then
    ok "G7 内存条报 anon 而非 current（anon=$((anon/1024/1024))M current=$((cur/1024/1024))M 显示=$((shown/1024/1024))M）"
  else
    bad "G7 显示 $((shown/1024/1024))M，anon=$((anon/1024/1024))M current=$((cur/1024/1024))M" "page cache 被当成了占用"
  fi
  rm -f "$tmpf" 2>/dev/null

  # G6 显式关闭要真的关掉
  s=$(ROAM_SESSION_MEM_MAX=off "$TTMUX" new "$TAG-g6" --detach --json 2>/dev/null \
      | python3 -c 'import json,sys;print(json.load(sys.stdin).get("session",""))' 2>/dev/null)
  d=$(cg_dir "$s")
  [ "$(cat "$d/memory.max" 2>/dev/null)" = "max" ] && ok "G6 ROAM_SESSION_MEM_MAX=off 时不设限" \
    || bad "G6 关不掉，memory.max=$(cat "$d/memory.max" 2>/dev/null)"
}

# ── R2 会话懒恢复 ──────────────────────────────────────────────────────
run_revive() {
  sect "R2 会话懒恢复"

  # 造一个休眠会话：建 → 记下 → 手工把台账改成「被重启带走」。
  # 不能真去重启机器，但 died_reason='host-restart' + 对得上的 epoch 就是那个状态。
  local s; s=$(mk r1)
  [ -z "$s" ] && { bad "R0 建不出测试会话"; return; }
  make_dormant "$s"

  # V1 休眠会话要出现在列表里，并带上「点开能不能接回对话」
  local listed
  listed=$("$TTMUX" ls --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
m=[x for x in d if x['name']=='$s']
print(m[0].get('state','') if m else 'missing')")
  [ "$listed" = "dormant" ] && ok "V1 休眠会话进列表且 state=dormant" \
    || bad "V1 列表里 state=$listed" "少了这一步，前端 dropDeadTokens 会把标签全丢掉"

  # V2 tree 接口必须和平铺接口一致。**会话列表走的是 tree**，
  # 两份实现各补各的就会出现「概览里有、点进项目又没了」。
  local in_tree
  in_tree=$("$TTMUX" ls --tree --json 2>/dev/null | python3 -c "
import json,sys
def w(ns):
    for n in ns: yield n; yield from w(n.get('children') or [])
print(sum(1 for r in w(json.load(sys.stdin)) if r['name']=='$s' and r.get('state')=='dormant'))")
  [ "$in_tree" = "1" ] && ok "V2 tree 接口同样认得它（与平铺一致）" \
    || bad "V2 tree 接口里找不到该休眠会话" "ls --json 与 ls --tree 是两份实现，别只补一处"

  # V3 恢复：新会话建出来、名字带过去、溯源记上
  local out new label from
  out=$("$TTMUX" db revive "$s" --json 2>/dev/null)
  new=$(echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("session",""))' 2>/dev/null)
  label=$(echo "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("label",""))' 2>/dev/null)
  from=$(db "select restored_from from sessions where id=?" "$new")
  if [ -n "$new" ] && tmux has-session -t "=$new" 2>/dev/null && [ "$from" = "$s" ]; then
    ok "V3 恢复出新会话（$label），restored_from 指回原会话"
  else
    bad "V3 new=$new from=$from" "期望新会话存在且 restored_from=$s"
  fi

  # V4 名字要落库，不能只是显示时现算。
  # 从前恢复出来的会话 label 是空的，列表里就退回一串裸 id。
  local dblabel; dblabel=$(db "select label from sessions where id=?" "$new")
  [ -n "$dblabel" ] && ok "V4 名字落进台账（label=$dblabel）" \
    || bad "V4 台账里 label 是空的" "兜底名只在显示时算的话，恢复前后会是两个名字"

  # V5 幂等：再点一次不该长出第二个会话
  local again reused
  again=$("$TTMUX" db revive "$s" --json 2>/dev/null)
  reused=$(echo "$again" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("session",""),d.get("reused",""))' 2>/dev/null)
  case "$reused" in
    "$new"*) ok "V5 幂等：再恢复一次复用同一个会话" ;;
    *)       bad "V5 又建了一个：$reused" "double-checked locking 没兜住" ;;
  esac

  # V6 恢复过的不再出现在休眠列表里（否则点一次多一个）
  local still
  still=$("$TTMUX" ls --json 2>/dev/null | python3 -c "
import json,sys
print(sum(1 for x in json.load(sys.stdin) if x['name']=='$s' and x.get('state')=='dormant'))")
  [ "$still" = "0" ] && ok "V6 已恢复的会话从休眠列表消失" \
    || bad "V6 它还在休眠列表里" "restored_from 被占用后就该排除，否则会重复恢复"

  # V8 **每一型 agent 都要能接回对话**，不只是 claude。
  #
  # 从前 revive 里硬编着 `claude --resume`、codex 直接跳过，理由写的是
  # 「codex 没有对应参数」——那句话在写下时是对的，可 codex 后来加了
  # `codex resume <SESSION_ID>`，假设过期了没人回头改。这条按注册表逐型验，
  # 新增一型忘了实现 ResumeCommand，红的是这里。
  local kinds
  kinds=$(python3 -c "
import subprocess,json
out=subprocess.run(['$ROAMI_BIN','session','agent','kinds','--json'],capture_output=True,text=True).stdout.strip()
print(out if out else '')" 2>/dev/null)
  if [ -z "$kinds" ]; then
    # 没有 CLI 子命令就直接按已知两型验（接口在 internal/agent 里已有单测覆盖全集）
    kinds="claude codex"
  fi
  local kind fake newid rcmd
  for kind in $kinds; do
    fake=$(mk "v8-$kind")
    [ -z "$fake" ] && { bad "V8 建不出 $kind 测试会话"; continue; }
    # 伪造一段该型的对话：给它一个 uuid + kind，再变成休眠
    newid="11111111-2222-3333-4444-$(printf '%012d' $RANDOM$RANDOM)"
    python3 - "$fake" "$kind" "$newid" <<'PYEOF'
import sqlite3,sys,os
sid,kind,cid=sys.argv[1],sys.argv[2],sys.argv[3]
c=sqlite3.connect(os.environ['TEST_DATABASE_PATH'])
c.execute("update sessions set agent_kind=?, agent_session_uuid=? where id=?",(kind,cid,sid))
c.commit()
PYEOF
    make_dormant "$fake"
    # 等它真的进了休眠列表再往下走。台账刚改完不代表列表立刻认——
    # Dormant() 只认「最新一代 epoch」，而上一轮用例可能刚写过一条更晚的。
    local resumable="" w2=0
    until [ "$resumable" = "True" ] || [ "$resumable" = "False" ] || [ $w2 -ge 8 ]; do
      resumable=$("$TTMUX" ls --json 2>/dev/null | python3 -c "
import json,sys
for r in json.load(sys.stdin):
    if r['name']=='$fake': print(r.get('resumable',False)); break
else: print('missing')")
      [ "$resumable" = "missing" ] && { sleep 1; w2=$((w2+1)); resumable=""; }
    done
    # 恢复，看 pane 里敲的是不是这一型自己的命令
    "$TTMUX" db revive "$fake" --json >/dev/null 2>&1
    local newsess
    newsess=$(db "select id from sessions where restored_from=?" "$fake")
    sleep 1
    local typed
    typed=$(tmux capture-pane -t "=$newsess:" -p 2>/dev/null | grep -m1 -oE "(claude --resume|codex resume) [0-9a-f-]+" | head -1)
    if [ "$resumable" = "True" ] && [ -n "$typed" ] && echo "$typed" | grep -q "$newid"; then
      ok "V8/$kind 标为可接回，且 pane 里敲的是「$typed」"
    else
      bad "V8/$kind resumable=$resumable 敲的是「${typed:-（没敲）}」" "期望这一型自己的 resume 命令且带上对话 id"
    fi
    [ -n "$newsess" ] && tmux kill-session -t "=$newsess" 2>/dev/null
  done

  # V7 显式 kill 掉的不该自己回来
  local k; k=$(mk r7)
  "$TTMUX" kill "$k" --yes >/dev/null 2>&1   # --yes：不带它会停在交互确认上，输出「已取消」; "$TTMUX" ls >/dev/null 2>&1
  local kreason kdormant
  kreason=$(db "select died_reason from sessions where id=?" "$k")
  kdormant=$("$TTMUX" ls --json 2>/dev/null | python3 -c "
import json,sys
print(sum(1 for x in json.load(sys.stdin) if x['name']=='$k' and x.get('state')=='dormant'))")
  if [ "$kreason" = "killed" ] && [ "$kdormant" = "0" ]; then
    ok "V7 显式 kill 的会话不进休眠列表（died_reason=killed）"
  else
    bad "V7 reason=$kreason 在休眠列表=$kdormant" "只有 host-restart 才该自动回来"
  fi
  tmux kill-session -t "=$new" 2>/dev/null
}

# ── UI（需要 chrome CLI + 服务在跑）────────────────────────────────────
run_ui() {
  sect "UI（chrome）"
  command -v roami >/dev/null || { skip "整组" "没有 chrome CLI"; return; }
  curl -sk -o /dev/null "https://127.0.0.1:${PORT:-13579}/" 2>/dev/null || { skip "整组" "服务没在跑"; return; }
  roami chrome eval "1" >/dev/null 2>&1 || { skip "整组" "Chrome 没起（roami chrome goto 一次即可）"; return; }

  # 自己造一个休眠会话再看——不能指望跑测试时环境里正好有一个，
  # 那样这条最该守的用例会长期停在 skip 上，等于没有。
  local probe; probe=$(mk ui1)
  [ -n "$probe" ] && make_dormant "$probe"

  # 掉登录就自己登回去：服务重启会清 session，而这组用例常跟在一次部署后面跑，
  # 不自愈的话它就变成「每次都要人先去点一下登录」，那种测试没人会跑。
  roami chrome goto "https://127.0.0.1:${PORT:-13579}/" >/dev/null 2>&1; sleep 3
  if roami chrome eval "!!document.querySelector('input[type=password]')" 2>/dev/null | grep -q true; then
    local pw; pw=$(grep -m1 '^TTMUX_WEB_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)
    if [ -n "$pw" ]; then
      roami chrome fill "input[type=password]" "$pw" >/dev/null 2>&1
      roami chrome click "button[type=submit], button:has-text('登 录')" >/dev/null 2>&1
      sleep 4
    else
      skip "整组" "在登录页且 .env 里读不到口令"; return
    fi
  fi

  roami chrome eval "location.hash='#/sessions'; 1" >/dev/null 2>&1; sleep 4
  local r
  r=$(roami chrome eval "
const rows=[...document.querySelectorAll('.tt-srow')];
const dor=rows.filter(r=>/休眠|Dormant/.test(r.querySelector('.tags')?.innerText||''));
const hollow=rows.filter(r=>{const i=r.querySelector('i');return i&&getComputedStyle(i).backgroundColor==='rgba(0, 0, 0, 0)'});
JSON.stringify({rows:rows.length,dormantTag:dor.length,hollow:hollow.length,membar:document.querySelectorAll('.tt-membar').length})
" 2>/dev/null | tail -1)
  local rows dtag hollow membar
  rows=$(echo "$r"   | python3 -c 'import json,sys;print(json.loads(sys.stdin.read().strip().strip(chr(39))).get("rows",0))' 2>/dev/null)
  dtag=$(echo "$r"   | python3 -c 'import json,sys;print(json.loads(sys.stdin.read().strip().strip(chr(39))).get("dormantTag",0))' 2>/dev/null)
  hollow=$(echo "$r" | python3 -c 'import json,sys;print(json.loads(sys.stdin.read().strip().strip(chr(39))).get("hollow",0))' 2>/dev/null)
  membar=$(echo "$r" | python3 -c 'import json,sys;print(json.loads(sys.stdin.read().strip().strip(chr(39))).get("membar",0))' 2>/dev/null)

  [ "${rows:-0}" -gt 0 ] && ok "U0 会话列表渲染出 $rows 行" || { bad "U0 列表是空的（没登录？）"; return; }

  # U1 是这次 bug 的直接回归：休眠会话曾经和活会话长得一模一样，
  # 标签同样写「空闲中」，用户点下去才发现要重开。
  if [ "${dtag:-0}" -gt 0 ]; then
    [ "$dtag" = "$hollow" ] && ok "U1 休眠会话有标签且状态点空心（$dtag 个）" \
      || bad "U1 休眠标签 $dtag 个但空心点 $hollow 个" "两者应当一一对应"
  else
    bad "U1 页面上认不出休眠会话" "刚造了一个休眠会话却没渲染出标签——正是「点下去才发现要重开」那个 bug"
  fi

  # U2 内存条：会话列表走 tree 接口，treeNode 漏字段的话这里恒为 0
  [ "${membar:-0}" -gt 0 ] && ok "U2 活会话渲染出内存条（$membar 个）" \
    || bad "U2 一个内存条都没有" "多半是 tree 接口漏了 mem 字段"

  # U3 主机监控面板不许再用硬编码颜色。
  #
  # swap 用满是整机卡死的前兆（2026-08-12 本机就是这么冻死的：ping 通、ssh 进不去），
  # 而它一度画成一根固定灰色的小条，98% 和 5% 长得一样。修好之后颜色全走令牌，
  # 这条盯的就是「别又有人写回 #f5222d」——AGENTS.md 的 tokens-only 在这里最容易破防，
  # 因为进度条颜色是行内 style，hover:check 那类静态扫描看不见。
  local hub="${HUB_URL:-}"
  if [ -z "$hub" ]; then
    skip "U3 主机监控颜色令牌化" "没给 HUB_URL（形如 https://<中心>:13570）"
  else
    roami chrome goto "$hub" >/dev/null 2>&1; sleep 3
    if roami chrome eval "!!document.querySelector('input[type=password]')" 2>/dev/null | grep -q true; then
      [ -n "${HUB_PASSWORD:-}" ] && {
        roami chrome fill "input[type=password]" "$HUB_PASSWORD" >/dev/null 2>&1
        roami chrome click "button[type=submit], button:has-text('登 录')" >/dev/null 2>&1; sleep 4
      }
    fi
    roami chrome eval "location.hash='#/hub'; 1" >/dev/null 2>&1; sleep 4
    roami chrome eval "const f=[...document.querySelectorAll('.tt-hub-fold')].find(x=>/这台机器|This machine/.test(x.innerText)); const b=f&&f.querySelector('button'); b&&b.click(); 1" >/dev/null 2>&1; sleep 4
    local hr
    hr=$(roami chrome eval "
const bars=[...document.querySelectorAll('.ant-progress-line .ant-progress-bg')].map(b=>b.style.background||b.style.backgroundColor);
JSON.stringify({swap:/Swap /.test(document.body.innerText),bars:bars.length,hard:bars.filter(b=>/#f5222d|#faad14/.test(b)).length})
" 2>/dev/null | tail -1)
    local hard swapshown
    hard=$(echo "$hr" | python3 -c 'import json,sys;print(json.loads(sys.stdin.read().strip().strip(chr(39))).get("hard",-1))' 2>/dev/null)
    swapshown=$(echo "$hr" | python3 -c 'import json,sys;print(json.loads(sys.stdin.read().strip().strip(chr(39))).get("swap",False))' 2>/dev/null)
    if [ "$swapshown" = "True" ] && [ "${hard:-1}" = "0" ]; then
      ok "U3 中心页画出 Swap 条，且颜色全走令牌"
    else
      bad "U3 swap显示=$swapshown 硬编码色=$hard" "期望 swap 条在且 0 个 #f5222d/#faad14"
    fi
  fi
}

case "${1:-all}" in
  guard)  run_guard ;;
  revive) run_revive ;;
  ui)     run_ui ;;
  all)    run_guard; run_revive; run_ui ;;
  *) echo "用法: $0 [all|guard|revive|ui]"; exit 2 ;;
esac

printf '\n\033[1m结果\033[0m  通过 %d · 失败 %d · 跳过 %d\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ]
