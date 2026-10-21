package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestIsolationLauncherDiscardsInheritedStorageRoots(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	dir := t.TempDir()
	t.Cleanup(func() { _ = exec.Command("bash", "../../scripts/dev/isolated-roami.sh", dir, "--stop").Run() })
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

func TestIsolatedCleanupKeepsOtherServerAlive(t *testing.T) {
	binary, err := exec.LookPath("tmux")
	if err != nil {
		t.Skip("tmux not installed")
	}
	host := filepath.Join(t.TempDir(), "host.sock")
	native := func(args ...string) []byte {
		t.Helper()
		output, err := exec.Command(binary, append([]string{"-S", host}, args...)...).CombinedOutput()
		if err != nil {
			t.Fatalf("host fixture: %v %s", err, output)
		}
		return output
	}
	native("new-session", "-d", "-s", "sentinel")
	t.Cleanup(func() { _ = exec.Command(binary, "-S", host, "kill-server").Run() })
	pid := strings.TrimSpace(string(native("display-message", "-p", "#{pid}")))
	root := t.TempDir()
	launcher := func(args ...string) *exec.Cmd {
		cmd := exec.Command("bash", append([]string{"../../scripts/dev/isolated-roami.sh", root}, args...)...)
		cmd.Env = append(os.Environ(), "TMUX="+host+","+pid+",0", "TMUX_BIN=/must-not-be-used", "TTMUX_BIN=/must-not-be-used")
		return cmd
	}
	t.Cleanup(func() { _ = launcher("--stop").Run() })
	output, err := launcher("sh", "-c", `"$TMUX_BIN" new-session -d -s test-session; tmux display-message -p '#{socket_path}'`).CombinedOutput()
	if err != nil {
		t.Fatalf("launch: %v %s", err, output)
	}
	if strings.Contains(string(output), host) {
		t.Fatalf("test command reached host socket: %s", output)
	}
	// A tampered manifest must never redirect cleanup to another socket.
	manifest := filepath.Join(root, "tmux-instance.json")
	saved, err := os.ReadFile(manifest)
	if err != nil {
		t.Fatal(err)
	}
	var state map[string]any
	if err = json.Unmarshal(saved, &state); err != nil {
		t.Fatal(err)
	}
	state["socket"] = host
	corrupt, _ := json.Marshal(state)
	if err = os.WriteFile(manifest, corrupt, 0600); err != nil {
		t.Fatal(err)
	}
	if output, err = launcher("--stop").CombinedOutput(); err == nil {
		t.Fatalf("tampered manifest accepted: %s", output)
	}
	native("has-session", "-t", "=sentinel")
	if err = os.WriteFile(manifest, saved, 0600); err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if output, err = launcher("--stop").CombinedOutput(); err != nil {
			t.Fatalf("cleanup: %v %s", err, output)
		}
		native("has-session", "-t", "=sentinel")
	}
}
