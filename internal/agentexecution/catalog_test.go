package agentexecution

import (
	"os"
	"path/filepath"
	"testing"
)

func TestExecutorDiscoveryDoesNotRunCommandsOrInferAccounts(t *testing.T) {
	dir := t.TempDir()
	marker := filepath.Join(dir, "executed")
	for _, name := range []string{"codex", "renderer"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("#!/bin/sh\ntouch '"+marker+"'\n"), 0700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", dir)
	catalog := DiscoverExecutors()
	found := false
	for _, candidate := range catalog.Candidates {
		if candidate.Authentication != "unknown" || candidate.Usage != "unknown" {
			t.Fatal("inferred account state")
		}
		if candidate.Kind == "codex" {
			found = candidate.Installed && candidate.Tracked
		}
		if candidate.Kind == "opencode" && candidate.Tracked {
			t.Fatal("unimplemented tracked adapter exposed")
		}
	}
	if !found {
		t.Fatal("installed Codex not discovered")
	}
	if err := catalog.ProbeCommands([]string{"renderer", "absent"}); err != nil {
		t.Fatal(err)
	}
	if !catalog.CommandAvailability["renderer"] || catalog.CommandAvailability["absent"] {
		t.Fatal(catalog.CommandAvailability)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("discovery executed an external command")
	}
	for _, command := range []string{"/bin/sh", "../renderer", "renderer --version", "$(id)"} {
		if err := catalog.ProbeCommands([]string{command}); err == nil {
			t.Fatalf("invalid command accepted: %s", command)
		}
	}
}

func TestNativeOpenCodeExecutorDiscovery(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PATH", t.TempDir())
	path := filepath.Join(home, ".opencode", "bin", "opencode")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("#!/bin/sh\nexit 99\n"), 0700); err != nil {
		t.Fatal(err)
	}
	catalog := DiscoverExecutors()
	found := false
	for _, candidate := range catalog.Candidates {
		if candidate.Kind == "opencode" {
			found = candidate.Installed && !candidate.Tracked && candidate.Authentication == "unknown"
		}
	}
	if !found {
		t.Fatal("native OpenCode not discovered")
	}
	if err := catalog.ProbeCommands([]string{"opencode"}); err != nil || catalog.CommandAvailability["opencode"] {
		t.Fatalf("bare command outside PATH reported available: %+v, %v", catalog.CommandAvailability, err)
	}
}
