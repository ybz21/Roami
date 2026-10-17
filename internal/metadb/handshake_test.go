package metadb

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	"github.com/ybz21/Roami/backend/ttmux"
)

// fakeCLI 写一个假 ttmux：db status 输出给定 JSON（或垃圾），其余命令空转。
func fakeCLI(t *testing.T, payload string) string {
	t.Helper()
	bin := filepath.Join(t.TempDir(), "ttmux")
	script := "#!/bin/sh\nif [ \"$1\" = db ]; then printf '%s' '" + payload + "'; fi\n"
	if err := os.WriteFile(bin, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return bin
}

// 库路径必须来自握手，不能由后端自己拼 —— ROAM_DATA 与 ROAM_HOME 可以指到
// 不同地方，自己拼会静悄悄开出一个空库，项目和会话全不见还查不出为什么。
// makeSchema 造一个够用的空库（后端不跑 DDL，测试里得自己摆一个）。
func makeSchema(t *testing.T, path string) {
	t.Helper()
	db, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(TestSchema); err != nil {
		t.Fatal(err)
	}
}

func TestPathComesFromHandshakeNotEnv(t *testing.T) {
	real := filepath.Join(t.TempDir(), "elsewhere.db")
	makeSchema(t, real)
	t.Setenv("ROAM_DATA", "/tmp/some-other-place")

	bin := fakeCLI(t, `{"path":"`+real+`","schemaVersion":3,"minCompatible":1,"journalMode":"wal"}`)
	d := Open(context.Background(), ttmux.New(bin), "")
	defer d.Close()
	if !d.OK() {
		t.Fatalf("应当直连成功: %s", d.Why())
	}
	if d.Info().Path != real {
		t.Fatalf("开的是 %q，应当是握手报的 %q", d.Info().Path, real)
	}
}

func TestDegradesWhenCLIMissing(t *testing.T) {
	d := Open(context.Background(), ttmux.New("/nonexistent/ttmux"), "")
	if d.OK() || d.Mode() != ModeLegacy {
		t.Fatal("CLI 不在时应退回 legacy 而不是崩")
	}
	if d.Why() == "" {
		t.Fatal("降级必须说明原因（用户要能在 /info 里看见）")
	}
}

func TestDegradesWhenCLITooOld(t *testing.T) {
	// 老 CLI 没有 db 子命令，输出会被 tmux 透传，不是 JSON
	d := Open(context.Background(), ttmux.New(fakeCLI(t, "usage: tmux ...")), "")
	if d.OK() {
		t.Fatal("输出不是 JSON 时应降级")
	}
}

func TestDegradesWhenSchemaTooNew(t *testing.T) {
	d := Open(context.Background(), ttmux.New(fakeCLI(t,
		`{"path":"/tmp/x.db","schemaVersion":99,"minCompatible":99}`)), "")
	if d.OK() {
		t.Fatal("库要求的读者版本高于本后端时应降级为只读/legacy")
	}
}
