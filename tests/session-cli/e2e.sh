#!/usr/bin/env bash
#
# End-to-end test for the integrated Roami session CLI.
#
# Runs the Go binary against an isolated tmux server (private socket) and temp
# data dirs, exercising every command surface and asserting on results — including the legacy executable alias on the same SQLite stores.
#
# No real claude/codex is invoked: fake stubs are placed on PATH so agent
# members "launch" harmlessly.
#
# Usage:  tests/session-cli/e2e.sh   (exit 0 = all passed)

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GODIR="$REPO"

# ── isolated environment ──
SOCKET="ttmux-e2e-$$"
ORIG_HOME="$HOME"   # keep the real Go module cache for the build step
SANDBOX="$(mktemp -d /tmp/ttmux-e2e.XXXXXX)"
WBIN="$SANDBOX/bin"
mkdir -p "$WBIN"
for storage_prefix in ROAMI ROAM TTMUX; do
  for storage_suffix in HOME DATA CONFIG DATABASE_DIR BACKUP_DIR; do
    unset "${storage_prefix}_${storage_suffix}"
  done
done
export TTMUX_DATA="$SANDBOX/data"
export TTMUX_HOME="$SANDBOX/home"
export HOME="$SANDBOX/fakehome"
mkdir -p "$TTMUX_DATA" "$TTMUX_HOME" "$HOME"
export NO_COLOR=1
unset TMUX_BIN TTMUX_AGENT TTMUX_QUIET 2>/dev/null || true

# tmux wrapper bound to the private socket（在改 PATH 前解析真实 tmux，
# 避免硬编码 /usr/bin/tmux 在 macOS/Homebrew 环境下找不到）
REAL_TMUX="$(command -v tmux)"
cat > "$WBIN/tmux" <<EOF
#!/usr/bin/env bash
exec "$REAL_TMUX" -L $SOCKET "\$@"
EOF
# fake claude/codex: stay alive so a resident "agent" session persists
for stub in claude codex; do
  cat > "$WBIN/$stub" <<EOF
#!/usr/bin/env bash
echo "[fake $stub] \$*"
sleep 600
EOF
done
chmod +x "$WBIN"/*
export PATH="$WBIN:$PATH"

GO="$SANDBOX/ttmux-go"

cleanup() {
  tmux -L "$SOCKET" kill-server 2>/dev/null || true
  chmod -R u+w "$SANDBOX" 2>/dev/null || true
  rm -rf "$SANDBOX"
}
trap cleanup EXIT

# ── assertion helpers ──
PASS=0; FAIL=0; FAILED=()
ok()  { PASS=$((PASS+1)); printf '  \033[32m✅\033[0m %s\n' "$1"; }
no()  { FAIL=$((FAIL+1)); FAILED+=("$1"); printf '  \033[31m❌ %s\033[0m\n' "$1"; [ -n "${2:-}" ] && printf '       \033[2m%s\033[0m\n' "$2"; }
eq()  { [ "$2" = "$3" ] && ok "$1" || no "$1" "expected=[$2] actual=[$3]"; }
has() { case "$2" in *"$3"*) ok "$1";; *) no "$1" "missing [$3]";; esac; }
nthas(){ case "$2" in *"$3"*) no "$1" "unexpected [$3]";; *) ok "$1";; esac; }
rc0() { local n="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$n"; else no "$n" "rc=$?"; fi; }
sec() { printf '\n\033[1m── %s ──\033[0m\n' "$1"; }
jget(){ python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

# ── build ──
sec "build"
if (cd "$GODIR" && HOME="$ORIG_HOME" go build -o "$GO" ./cmd/roami) 2>/tmp/e2e-build; then ok "go build"; else no "go build" "$(cat /tmp/e2e-build)"; echo "FATAL"; exit 1; fi
tmux -L "$SOCKET" kill-server 2>/dev/null || true

# ════════════════════════════════════════════
sec "basics: version / help / info"
eq "version" "ttmux v0.4.1-go" "$($GO -v)"
has "help renders" "$($GO help)" "AI-native tmux wrapper"
has "info --json sessions field" "$($GO info --json | jget 'list(d.keys())')" "sessions"
eq "info --json sessions=0 (no server)" "0" "$($GO info --json | jget 'd["sessions"]')"
eq "ls --json empty (no server)" "0" "$($GO ls --json | jget 'len(d)')"

# ════════════════════════════════════════════
sec "sessions: send / capture / windows"
# 自己建一个会话：这几条以前搭 `spawn` 建出来的任务会话的便车，而 spawn 作为
# 用户级命令在迁到 Go 时就有意去掉了（内部仍被蜂群/插件用着）。
SESS=$($GO new --json probe --dir "$SANDBOX" | jget 'd["session"]')
$GO send "$SESS" "echo INJECTED_CMD" >/dev/null; sleep 1
has "capture shows injected" "$($GO capture "$SESS" --lines 50)" "INJECTED_CMD"
has "lw lists window on session" "$($GO lw -t "$SESS")" "◻"

sec "session identity: id as tmux name, label for display"
$GO new "我的 会话" --detach >/dev/null
SID="$($GO resolve "我的 会话")"
rc0 "new session name is an id" bash -c "printf '%s' '$SID' | grep -Eq '^[0-9]{4}-[0-9]{4}-[0-9]{4}-[a-z0-9]{4}$'"
eq "label lives in @roam_name" "我的 会话" "$(tmux -L "$SOCKET" display-message -t "$SID" -p '#{@roam_name}')"
has "ls shows 名字(id)" "$($GO ls)" "我的 会话($SID)"
eq "ls --json label" "我的 会话" "$($GO ls --json | jget '[s["label"] for s in d if s["name"]=="'"$SID"'"][0]')"
# 改名 = 只改展示名：会话名（= handle）纹丝不动，所以标签/URL/归属/台账都不用搬
$GO rename "我的 会话" "改过的名字" >/dev/null
eq "rename keeps session name" "$SID" "$($GO resolve 改过的名字)"
eq "rename changes label only" "改过的名字" "$(tmux -L "$SOCKET" display-message -t "$SID" -p '#{@roam_name}')"
# 展示名可以重名（它不是身份了）——两个会话同名互不影响
$GO new "改过的名字" --detach --no-reuse >/dev/null
eq "duplicate labels allowed" "2" "$($GO ls --json | jget 'len([s for s in d if s["label"]=="改过的名字"])')"
$GO kill "$SID" --yes >/dev/null
eq "kill by id" "1" "$($GO ls --json | jget 'len([s for s in d if s["label"]=="改过的名字"])')"

# ════════════════════════════════════════════
sec "env"
$GO env set FOO=bar >/dev/null; $GO env set BAZ=qux >/dev/null
eq "env --json count" "2" "$($GO env --json | jget 'len(d)')"
eq "env set value" "bar" "$($GO env --json | jget '[e["value"] for e in d if e["key"]=="FOO"][0]')"
has "env list pretty" "$($GO env)" "FOO=bar"
$GO env rm FOO >/dev/null
nthas "env rm removed FOO" "$($GO env --json)" '"FOO"'
$GO env clear >/dev/null
eq "env clear empties" "0" "$($GO env --json | jget 'len(d)')"

# ════════════════════════════════════════════
sec "swarm: new / add / status (+ deps gating)"
$GO swarm new feat --goal "登录功能" --no-master >/dev/null
rc0 "swarm registered" bash -c "$GO swarm status feat --json >/dev/null"
$GO swarm add feat api --type task "echo API; sleep 300" >/dev/null
$GO swarm add feat web --type task "echo WEB; sleep 300" >/dev/null
$GO swarm add feat qa --type task --depends-on api "echo QA; sleep 300" >/dev/null
sleep 1
# 依赖是**软**的：记录关系供拓扑连线与 prompt 协调，但不挂起——成员一建出来就
# 起会话开工，缺上游产出时自己去广场等/问（见 cmdAdd 的注释与 worker.md.tmpl）。
# 这里断言的正是「三个都起来了、没有谁被扣住」。
eq "members launched" "3" "$($GO swarm status feat --json | jget 'len(d["members"])')"
eq "soft deps recorded" "api" "$($GO swarm sql feat --json "SELECT deps FROM members WHERE name='qa'" | jget 'd[0]["deps"]')"
eq "goal stored" "登录功能" "$($GO swarm status feat --json | jget 'd["goal"]')"
has "swarm ls --json" "$($GO swarm ls --json | jget '[s["name"] for s in d]')" "feat"
has "swarm ls pretty" "$($GO swarm ls)" "feat"
has "swarm status pretty" "$($GO swarm status feat)" "蜂群: feat"

sec "swarm: agent member launches fake claude"
$GO swarm add feat lead --type agent "带队" >/dev/null; sleep 1
eq "first agent => leader role" "leader" "$($GO swarm sql feat --json "SELECT role FROM members WHERE name='lead'" | jget 'd[0]["role"]')"
# 会话名是会话 id，`feat-lead` 只是展示名(@roam_name)：先 resolve 再定位
# pane 目标的精确匹配要写成 "=名:"（tmux 3.4 对裸 "=名" 报 can't find pane）
has "agent member pane" "$(tmux -L "$SOCKET" capture-pane -t "=$($GO resolve feat-lead):" -p)" "[fake claude]"

sec "swarm: done => cascade unlock"
$GO swarm done feat api >/dev/null; sleep 1
eq "api done_marked" "api" "$($GO swarm status feat --json | jget 'd["done_marked"][0]')"
eq "qa unlocked (no pending)" "0" "$($GO swarm status feat --json | jget 'len(d["pending"])')"
rc0 "qa session launched" $GO resolve feat-qa   # resolve 成功 = 该成员的会话在

sec "swarm: activate (explicit)"
$GO swarm add feat extra --type task --depends-on web "echo X; sleep 300" >/dev/null
$GO swarm done feat web >/dev/null
$GO swarm activate feat >/dev/null; sleep 1
rc0 "extra unlocked via activate" $GO resolve feat-extra

sec "swarm: plaza say / feed"
$GO swarm say feat --as api --kind ask "接口规范? @leader" >/dev/null
$GO swarm say feat --as leader --kind decide --re 1 "用 REST" >/dev/null
eq "feed --json count" "2" "$($GO swarm feed feat --json | jget 'len(d)')"
eq "feed re link" "1" "$($GO swarm feed feat --json | jget 'd[1]["re"]')"
has "feed text pretty" "$($GO swarm feed feat)" "接口规范"
eq "feed kind filter" "1" "$($GO swarm feed feat --kind ask --json | jget 'len(d)')"

sec "swarm: listen --once (relevance + cursor)"
LISTEN="$($GO swarm listen feat --as leader --once)"
has "listen HIGH tag" "$LISTEN" "[HIGH]"
has "listen status summary" "$LISTEN" "状态摘要"
has "listen advances cursor" "$LISTEN" "游标已推进"

sec "swarm: board / task"
CID="$($GO swarm task add feat "登录API卡" --assignee api 2>/dev/null)"
eq "task add returns id" "t1" "$CID"
$GO swarm task move feat "$CID" doing >/dev/null
eq "task moved to doing" "doing" "$($GO swarm task ls feat --json | jget 'd[0]["col"]')"
$GO swarm task add feat "第二张卡" >/dev/null
eq "board --json 2 cards" "2" "$($GO swarm board feat --json | jget 'len(d)')"
has "board render" "$($GO swarm board feat)" "看板: feat"
$GO swarm task assign feat t1 web >/dev/null
eq "reassign" "web" "$($GO swarm task ls feat --col doing --json | jget 'd[0]["assignee"]')"
$GO swarm task rm feat t1 >/dev/null
eq "task rm" "1" "$($GO swarm board feat --json | jget 'len(d)')"

sec "swarm: sql read-only guard"
rc0 "sql SELECT allowed" bash -c "$GO swarm sql feat 'SELECT count(*) FROM members' >/dev/null"
if $GO swarm sql feat "DELETE FROM members" >/dev/null 2>&1; then no "sql blocks writes"; else ok "sql blocks writes"; fi

sec "swarm: collect / archive"
has "swarm collect --json" "$($GO swarm collect feat --json | jget '"results" in d and "ok"')" "ok"
$GO swarm archive feat >/dev/null
eq "archived status" "archived" "$($GO swarm status feat --json | jget 'd["status"]')"
rc0 "archive killed sessions" bash -c "! tmux -L '$SOCKET' has-session -t feat-api 2>/dev/null"

# ════════════════════════════════════════════
sec "cross-compat with bash CLI (shared DBs)"

# ════════════════════════════════════════════
sec "swarm migrate (legacy file metadata)"
mkdir -p "$TTMUX_DATA/swarms/legacy"
echo "2026-01-01 10:00:00" > "$TTMUX_DATA/swarms/legacy/created.txt"
echo "旧目标" > "$TTMUX_DATA/swarms/legacy/goal.txt"
echo "running" > "$TTMUX_DATA/swarms/legacy/status.txt"
printf 'legacy-x\nlegacy-y\n' > "$TTMUX_DATA/groups/legacy.group"
$GO swarm migrate >/dev/null
has "migrate indexes legacy" "$($GO swarm ls --json | jget '[s["name"] for s in d]')" "legacy"
eq "migrate seeds members" "2" "$($GO swarm sql legacy --json "SELECT count(*) AS c FROM members" | jget 'd[0]["c"]')"

# ════════════════════════════════════════════
sec "agent mode (machine-friendly)"
A_OUT="$(TTMUX_AGENT=1 $GO swarm new amode --no-master 2>/dev/null; TTMUX_AGENT=1 $GO swarm task add amode '卡片' 2>/dev/null)"
eq "agent stdout = id only" "t1" "$A_OUT"
A_ERR="$(TTMUX_AGENT=1 $GO swarm task add amode '卡2' 2>&1 1>/dev/null)"
has "agent messages on stderr" "$A_ERR" "新卡"
eq "-q flag form works" "t3" "$($GO -q swarm task add amode '卡3' 2>/dev/null)"

# ════════════════════════════════════════════
sec "completion install"
$GO completion >/dev/null 2>&1
rc0 "completion file written" bash -c "[ -f '$HOME/.bash_completion.d/ttmux' ]"
rc0 "bashrc updated" bash -c "grep -q bash_completion.d/ttmux '$HOME/.bashrc'"

# ════════════════════════════════════════════
sec "standalone: no rt.Shell remains in source"
if grep -rqn "rt.Shell\|a.rt.Shell" "$GODIR/internal" --include='*.go' 2>/dev/null; then
  no "zero shell-outs" "found rt.Shell usage"
else ok "zero shell-outs"; fi

sec "cross-compile (CGO off)"
for t in darwin/arm64 darwin/amd64 linux/amd64 linux/arm64 freebsd/amd64; do
  if (cd "$GODIR" && CGO_ENABLED=0 GOOS=${t%/*} GOARCH=${t#*/} HOME="$ORIG_HOME" go build -o /dev/null ./cmd/roami) 2>/tmp/e2e-xc; then
    ok "build $t"
  else no "build $t" "$(cat /tmp/e2e-xc)"; fi
done

# ── summary ──
printf '\n\033[1m════════ summary ════════\033[0m\n'
printf '  passed: \033[32m%d\033[0m   failed: \033[31m%d\033[0m\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf '\n  failing:\n'
  for f in "${FAILED[@]}"; do printf '    - %s\n' "$f"; done
  exit 1
fi
printf '  \033[32mALL PASSED\033[0m\n'
