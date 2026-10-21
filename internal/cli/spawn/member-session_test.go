package spawn

import (
	"context"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestMemberSessionExecutesItsTask(t *testing.T) {
	if os.Getenv("ROAMI_SPAWN_TEST_CHILD") != "1" {
		if _, err := exec.LookPath("tmux"); err != nil {
			t.Skip("tmux not installed")
		}
		root := t.TempDir()
		launcher := "../../../scripts/dev/isolated-roami.sh"
		t.Cleanup(func() { _ = exec.Command("bash", launcher, root, "--stop").Run() })
		binary, err := os.Executable()
		if err != nil {
			t.Fatal(err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, "bash", launcher, root, binary, "-test.run=^TestMemberSessionExecutesItsTask$")
		cmd.Env = append(os.Environ(), "ROAMI_SPAWN_TEST_CHILD=1")
		if output, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("isolated member: %v\n%s", err, output)
		}
		return
	}

	rt := runtime.New()
	receipt := filepath.Join(rt.DataDir, "member-receipt.txt")
	quoted := "'" + strings.ReplaceAll(receipt, "'", "'\\''") + "'"
	created, session, err := One(rt, "guide", "worker", "task", "printf spawn-ok > "+quoted, DefaultAgentConfig(rt.DataDir), io.Discard)
	if err != nil || !created || !rt.HasSession(session) {
		t.Fatalf("member did not start: created=%v session=%q err=%v", created, session, err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if data, err := os.ReadFile(receipt); err == nil && string(data) == "spawn-ok" {
			return
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatal("member session never executed its submitted command")
}
