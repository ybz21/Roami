package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestIsolationLauncherDiscardsInheritedStorageRoots(t *testing.T) {
	dir := t.TempDir()
	cmd := exec.Command("bash", "../../scripts/dev/isolated-roami.sh", dir, "sh", "-c", `printf '%s\n' "$ROAMI_HOME" "$ROAMI_DATA" "$ROAMI_CONFIG" "$ROAMI_DATABASE_DIR" "$ROAMI_BACKUP_DIR" "${ROAM_DATA-unset}" "${TTMUX_HOME-unset}"`)
	cmd.Env = append(os.Environ(), "ROAMI_DATA=/not-the-test-instance", "ROAMI_DATABASE_DIR=/not-the-test-database", "ROAM_DATA=/old-data", "TTMUX_HOME=/old-home")
	out, e := cmd.CombinedOutput()
	if e != nil {
		t.Fatalf("launcher: %v %s", e, out)
	}
	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	if len(lines) != 7 {
		t.Fatalf("paths=%s", out)
	}
	for _, path := range lines[:5] {
		rel, e := filepath.Rel(dir, path)
		if e != nil || rel == ".." || strings.HasPrefix(rel, "../") {
			t.Fatalf("escaped isolation: %s", path)
		}
	}
	if lines[5] != "unset" || lines[6] != "unset" {
		t.Fatalf("inherited legacy roots: %s", out)
	}
}
