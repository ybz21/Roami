package plugin

import (
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestHostSessionsAreScopedToInstance(t *testing.T) {
	root := t.TempDir()
	a := NewEnv(runtime.Runtime{HomeDir: filepath.Join(root, "a"), DataDir: filepath.Join(root, "a")})
	b := NewEnv(runtime.Runtime{HomeDir: filepath.Join(root, "b"), DataDir: filepath.Join(root, "b")})
	for _, base := range []string{DaemonSession, IMListenerSession, KeepaliveSession} {
		if a.HostSession(base) == b.HostSession(base) {
			t.Fatalf("shared host session for %s", base)
		}
	}
	if a.SockPath() == b.SockPath() {
		t.Fatal("shared control socket")
	}
}

func TestHostCommandPinsPathsAndQuotesShellArguments(t *testing.T) {
	root := filepath.Join(t.TempDir(), "developer's instance")
	for _, key := range []string{"HOME", "DATA", "CONFIG", "DATABASE_DIR", "BACKUP_DIR"} {
		t.Setenv("ROAMI_"+key, "/another-instance")
	}
	env := NewEnv(runtime.Runtime{HomeDir: root, DataDir: root})
	command, err := env.hostCommand("/bin/sh", "-c", `printf '%s\n' "$ROAMI_HOME" "$ROAMI_DATA" "$ROAMI_DATABASE_DIR" "$ROAMI_BACKUP_DIR" "$ROAMI_CONFIG"`)
	if err != nil {
		t.Fatal(err)
	}
	out, err := exec.Command("/bin/sh", "-c", command).CombinedOutput()
	if err != nil {
		t.Fatalf("%s: %v", out, err)
	}
	want := strings.Join([]string{root, root, filepath.Join(root, "database"), filepath.Join(root, "backups"), filepath.Join(root, "config.yaml"), ""}, "\n")
	if string(out) != want {
		t.Fatalf("paths=%q want=%q", out, want)
	}
}
