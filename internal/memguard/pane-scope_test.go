package memguard

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestMemoryLimitsRequireAnIsolatedPaneScope(t *testing.T) {
	const root = "/user.slice/user-1000.slice/user@1000.service/app.slice/"
	const pane = root + "tmux-spawn-pane.scope"
	const other = root + "tmux-spawn-other.scope"
	for _, tc := range []struct {
		name, scope, controller, parent string
		allowed                         bool
	}{
		{"isolated pane", pane, other, other, true},
		{"service controller", pane, root + "roami.service", other, true},
		{"inherited controller scope", pane, pane, other, false},
		{"nested controller", pane, pane + "/child", other, false},
		{"inherited server scope", pane, other, pane, false},
		{"nested server", pane, other, pane + "/child", false},
		{"login scope", root + "session-1.scope", other, other, false},
		{"service", root + "roami.service", other, other, false},
		{"unknown controller", pane, "", other, false},
		{"unknown parent", pane, other, "", false},
		{"unknown pane", "", other, other, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := validateMemoryScope(tc.scope, tc.controller, tc.parent)
			if (err == nil) != tc.allowed {
				t.Fatalf("allowed=%v, err=%v", tc.allowed, err)
			}
		})
	}
}

func TestMemoryScopeRefusesTheCallingProcess(t *testing.T) {
	if unit, err := memoryScope(os.Getpid()); err == nil {
		t.Fatalf("controller scope accepted: %s", unit)
	}
}

func TestMemoryLimitsNeverWriteTheControllerScope(t *testing.T) {
	if !strings.HasPrefix(ScopeOf(os.Getpid()), "tmux-spawn-") || !available() {
		t.Skip("requires a tmux pane with delegated memory controls")
	}
	dir := t.TempDir()
	marker := filepath.Join(dir, "writes")
	if err := os.WriteFile(filepath.Join(dir, "systemctl"), []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$MEMGUARD_TEST_WRITES\"\n"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("MEMGUARD_TEST_WRITES", marker)
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	for _, change := range []struct {
		name string
		run  func() error
	}{
		{"hard limit", func() error { return Apply(os.Getpid(), From("128M", "96M", "0")) }},
		{"soft limit", func() error { return SetHigh(os.Getpid(), 96<<20) }},
	} {
		t.Run(change.name, func(t *testing.T) {
			if err := change.run(); err == nil {
				t.Fatal("controller scope was accepted")
			}
			if _, err := os.Stat(marker); !os.IsNotExist(err) {
				t.Fatalf("systemctl was called on the controller scope: %v", err)
			}
		})
	}
}
