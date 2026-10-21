package ttmux

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func localClient(t *testing.T, program string) *Client {
	t.Helper()
	root := t.TempDir()
	for _, prefix := range []string{"ROAMI", "ROAM", "TTMUX"} {
		for _, suffix := range []string{"HOME", "DATA", "CONFIG", "DATABASE_DIR", "BACKUP_DIR"} {
			t.Setenv(prefix+"_"+suffix, "")
		}
	}
	t.Setenv("ROAMI_HOME", root)
	binary := filepath.Join(root, "tmux")
	if e := os.WriteFile(binary, []byte("#!/bin/sh\n"+program), 0700); e != nil {
		t.Fatal(e)
	}
	t.Setenv("TMUX_BIN", binary)
	return New("roami")
}
func TestLocalNativeTmuxOutputIsReturnedToHTTPAdapter(t *testing.T) {
	c := localClient(t, "case \"$1\" in\n list-sessions|has-session) exit 1;;\n display-message) printf '/expected/cwd\\n';;\n esac\n")
	out, e := c.RunCtx(context.Background(), "display-message", "-p", "#{pane_current_path}")
	if e != nil || strings.TrimSpace(out) != "/expected/cwd" {
		t.Fatalf("native output=%q error=%v", out, e)
	}
}
func TestLocalNativeTmuxHonorsContext(t *testing.T) {
	c := localClient(t, "case \"$1\" in\n list-sessions|has-session) exit 1;;\n display-message) exec sleep 10;;\n esac\n")
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	started := time.Now()
	if _, e := c.RunCtx(ctx, "display-message", "-p", "x"); e == nil {
		t.Fatal("cancellation returned success")
	}
	if time.Since(started) > time.Second {
		t.Fatal("native command ignored context")
	}
}

func TestAdapterRejectsGlobalTmuxOperations(t *testing.T) {
	c := localClient(t, "echo should-not-run\n")
	for _, command := range []string{"kill-server", "killall", "kill-session", "source-file", "run-shell"} {
		if output, err := c.Run(command); err == nil || strings.Contains(output, "should-not-run") {
			t.Fatalf("operation %s reached tmux: %q %v", command, output, err)
		}
	}
}
