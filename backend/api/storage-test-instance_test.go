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
	root, e := os.MkdirTemp("", "roami-api-tests-*")
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
	for _, prefix := range []string{"ROAMI", "ROAM", "TTMUX"} {
		for _, suffix := range []string{"HOME", "DATA", "CONFIG", "DATABASE_DIR", "BACKUP_DIR"} {
			_ = os.Unsetenv(prefix + "_" + suffix)
		}
	}
	for key, value := range map[string]string{"ROAMI_HOME": root, "ROAMI_DATA": root, "ROAMI_CONFIG": filepath.Join(root, "config.yaml"), "ROAMI_DATABASE_DIR": filepath.Join(root, "database"), "ROAMI_BACKUP_DIR": filepath.Join(root, "backups"), "TMUX": ""} {
		_ = os.Setenv(key, value)
	}
	var tmux, socket string
	if binary, err := exec.LookPath("tmux"); err == nil {
		tmux = binary
		socket = fmt.Sprintf("roami-api-tests-%d", os.Getpid())
		wrapper := filepath.Join(root, "tmux")
		if err = os.WriteFile(wrapper, []byte("#!/bin/sh\nexec "+shellQuote(binary)+" -L "+socket+" \"$@\"\n"), 0700); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		_ = os.Setenv("TMUX_BIN", wrapper)
	}
	code := m.Run()
	if tmux != "" {
		_ = exec.Command(tmux, "-L", socket, "kill-server").Run()
	}
	_ = os.RemoveAll(root)
	os.Exit(code)
}
