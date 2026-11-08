package api

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	metadb "github.com/ybz21/Roami/internal/storage"
)

func isolateTestStorage(t *testing.T, root string) {
	t.Helper()
	for _, prefix := range []string{"ROAMI", "ROAM", "TTMUX"} {
		for _, suffix := range []string{"HOME", "DATA", "CONFIG", "DATABASE_DIR", "BACKUP_DIR"} {
			t.Setenv(prefix+"_"+suffix, "")
		}
	}
	t.Setenv("ROAMI_HOME", root)
	t.Setenv("ROAMI_DATA", root)
	t.Setenv("ROAMI_DATABASE_DIR", filepath.Join(root, "database"))
	t.Setenv("ROAMI_BACKUP_DIR", filepath.Join(root, "backups"))
	t.Setenv("ROAMI_CONFIG", filepath.Join(root, "config.yaml"))
	p, e := metadb.ResolvePaths("", "")
	if e != nil {
		t.Fatal(e)
	}
	for _, path := range []string{p.Home, p.Data, p.Database, p.Backup} {
		rel, e := filepath.Rel(root, path)
		if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || filepath.IsAbs(rel) {
			t.Fatalf("test escaped instance: %s", path)
		}
	}
}

func TestMain(m *testing.M) {
	if os.Getenv("ROAMI_API_TEST_ISOLATED") == "1" {
		os.Exit(m.Run())
	}
	root, e := os.MkdirTemp("", "roami-api-tests-*")
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
	if _, err := exec.LookPath("tmux"); err != nil {
		for _, prefix := range []string{"ROAMI", "ROAM", "TTMUX"} {
			for _, suffix := range []string{"HOME", "DATA", "CONFIG", "DATABASE_DIR", "BACKUP_DIR"} {
				_ = os.Unsetenv(prefix + "_" + suffix)
			}
		}
		for key, value := range map[string]string{"ROAMI_HOME": root, "ROAMI_DATA": root, "ROAMI_DATABASE_DIR": filepath.Join(root, "database"), "ROAMI_BACKUP_DIR": filepath.Join(root, "backups"), "ROAMI_CONFIG": filepath.Join(root, "config.yaml"), "TMUX": "", "TMUX_BIN": filepath.Join(root, "no-tmux")} {
			_ = os.Setenv(key, value)
		}
		code := m.Run()
		_ = os.RemoveAll(root)
		os.Exit(code)
	}
	launcher, _ := filepath.Abs("../../scripts/dev/isolated-roami.sh")
	args := append([]string{root, "env", "ROAMI_API_TEST_ISOLATED=1", os.Args[0]}, os.Args[1:]...)
	cmd := exec.Command(launcher, args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	code := 0
	if err := cmd.Run(); err != nil {
		code = 1
		if exit, ok := err.(*exec.ExitError); ok {
			code = exit.ExitCode()
		}
	}
	if out, err := exec.Command(launcher, root, "--stop").CombinedOutput(); err != nil {
		fmt.Fprintf(os.Stderr, "isolated cleanup: %v %s\n", err, out)
		code = 1
	}
	_ = os.RemoveAll(root)
	os.Exit(code)
}
