package runtime

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/ybz21/Roami/internal/id"
)

// fakeTmux 造一个只认 list-sessions -F 的假 tmux：把 state 文件里的
// "id<TAB>created<TAB>name<TAB>label" 按格式串渲染出来，够 SessionRows/Resolve 用。
func fakeTmux(t *testing.T, rows string) Runtime {
	t.Helper()
	dir := t.TempDir()
	state := filepath.Join(dir, "sessions.tsv")
	if err := os.WriteFile(state, []byte(rows), 0o644); err != nil {
		t.Fatal(err)
	}
	script := `#!/usr/bin/env bash
if [ "$1" != "list-sessions" ]; then exit 0; fi
fmt="$3"
while IFS=$'\t' read -r sid created name label; do
  [ -z "$sid" ] && continue
  line="$fmt"
  line=${line//'#{session_id}'/$sid}
  line=${line//'#{session_created}'/$created}
  line=${line//'#{session_name}'/$name}
  line=${line//'#{@roam_name}'/$label}
  printf '%s\n' "$line"
done < "` + state + `"
`
	bin := filepath.Join(dir, "tmux")
	if err := os.WriteFile(bin, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return Runtime{TmuxBin: bin, DataDir: dir, HomeDir: dir}
}

const sampleCreated = 1785233330

const sampleRows = "$0\t1785233330\t2026-0728-1808-0000\t我的会话\n" +
	"$1\t1785233330\t2026-0728-1808-0001\t研究-a\n" +
	"$2\t1785233330\t老会话\t\n" // 迁移前的老会话：名字不是 id、没有展示名

// legacyID 老会话现算出来的派生 id。不能写死——它的日期段按**本地时区**格式化，
// 写死会让 CI（UTC）与开发机（+08）对不上。
var legacyID = id.ForSession(sampleCreated, "$2")

func TestSessionRowsParsesLabels(t *testing.T) {
	rows := fakeTmux(t, sampleRows).SessionRows()
	if len(rows) != 3 {
		t.Fatalf("解析出 %d 行，want 3: %+v", len(rows), rows)
	}
	if rows[0].Label != "我的会话" || rows[0].TmuxID != "$0" {
		t.Fatalf("第一行解析错: %+v", rows[0])
	}
	// 展示名带空格/中文都不该被截断；没设 @roam_name 的退回会话名
	if got := rows[2].DisplayLabel(); got != "老会话" {
		t.Fatalf("无 label 时 DisplayLabel = %q, want 老会话", got)
	}
	// 老会话的 id 现算派生（与 `ls` 一直以来展示的 id 同一个值）
	if got := rows[2].ID(); got != legacyID || !id.Valid(got) {
		t.Fatalf("派生 id = %q, want %q", got, legacyID)
	}
	if got := rows[0].Display(); got != "我的会话(2026-0728-1808-0000)" {
		t.Fatalf("Display = %q", got)
	}
}

// Resolve 是「全部会话都叫 id」能落地的关键：老用法（按语义名/老名字/派生 id 调用）
// 必须继续命中，否则 cc-swarm 的 `roami session send <群>-<成员>` 这类调用全断。
func TestResolveAcceptsEveryHandle(t *testing.T) {
	rt := fakeTmux(t, sampleRows)
	cases := map[string]string{
		"2026-0728-1808-0001": "2026-0728-1808-0001", // 会话名本身
		"研究-a":                "2026-0728-1808-0001", // 展示名
		"$0":                  "2026-0728-1808-0000", // tmux session_id
		"老会话":                 "老会话",                 // 迁移前的老会话：名字即会话名
		legacyID:              "老会话",                 // 老会话的派生 id（老书签/URL）
	}
	for token, want := range cases {
		if got := rt.Resolve(token); got != want {
			t.Errorf("Resolve(%q) = %q, want %q", token, got, want)
		}
	}
	// 解析不出来就原样奉还，让下游报「会话不存在」，不要瞎猜一个
	if got := rt.Resolve("不存在的东西"); got != "不存在的东西" {
		t.Errorf("未知 token 应原样返回，得到 %q", got)
	}
}

// tmux 盲态（server 没起）不能把 token 猜成别的东西。
func TestResolveBlindPassesThrough(t *testing.T) {
	rt := Runtime{TmuxBin: filepath.Join(t.TempDir(), "no-such-tmux")}
	if got := rt.Resolve("研究-a"); got != "研究-a" {
		t.Fatalf("盲态 Resolve = %q", got)
	}
}

// 展示名允许重复（它不再是身份）：多个同名时取稳定的第一个，不能随机漂。
func TestResolveDuplicateLabelIsStable(t *testing.T) {
	rt := fakeTmux(t, "$1\t1785233330\t2026-0728-1808-0001\tdev\n$0\t1785233330\t2026-0728-1808-0000\tdev\n")
	first := rt.Resolve("dev")
	if first != "2026-0728-1808-0000" {
		t.Fatalf("同名取值 = %q, want 最小会话名", first)
	}
	if again := rt.Resolve("dev"); again != first {
		t.Fatalf("同名解析不稳定: %q → %q", first, again)
	}
}

func TestSanitizeLabelKeepsHumanText(t *testing.T) {
	if got := SanitizeLabel("  dev 前端: v1.2  "); got != "dev 前端: v1.2" {
		t.Fatalf("SanitizeLabel = %q（空格/点号/冒号都该保留，它不是 tmux 目标了）", got)
	}
	if got := SanitizeLabel("a\tb\nc"); got != "a b c" {
		t.Fatalf("制表/换行会破坏 list-sessions -F 的分隔，必须替掉: %q", got)
	}
}

// 只有 tmux 那两句「连不上 socket」算 server 不在；权限不对、别的报错都不算——
// 认错了就会把一整表活会话误收进历史。
func TestNoServer(t *testing.T) {
	for _, out := range []string{
		"no server running on /tmp/tmux-1000/default\n",
		"error connecting to /tmp/tmux-1000/default (No such file or directory)\n",
	} {
		if !NoServer(out) {
			t.Errorf("应判为 server 不在: %q", out)
		}
	}
	for _, out := range []string{
		"",
		"error connecting to /tmp/tmux-1000/default (Permission denied)\n",
		"can't find session: dev\n",
		"dev\t1\t1700000000\n",
	} {
		if NoServer(out) {
			t.Errorf("不该判为 server 不在: %q", out)
		}
	}
}
