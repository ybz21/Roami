package agentinventory

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func TestProfessionalInstallArgs(t *testing.T) {
	for kind, want := range map[string][]string{
		"codex":    {"install", "-g", "@openai/codex"},
		"claude":   {"install", "-g", "@anthropic-ai/claude-code"},
		"opencode": {"install", "-g", "opencode-ai"},
		"pi":       {"install", "-g", "--ignore-scripts", "@earendil-works/pi-coding-agent"},
	} {
		got, err := ProfessionalInstallArgs(kind)
		if err != nil || !reflect.DeepEqual(got, want) {
			t.Fatalf("%s: %v, %v", kind, got, err)
		}
	}
	for _, kind := range []string{"", "unknown", "codex;echo injected", "--prefix=/tmp"} {
		if _, err := ProfessionalInstallArgs(kind); err == nil {
			t.Fatalf("accepted unsupported kind %q", kind)
		}
	}
}

func TestAutomaticVersionDiscoveryDoesNotImplyAuthentication(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("HOME", t.TempDir())
	marker := filepath.Join(dir, "version-ran")
	path := filepath.Join(dir, "codex")
	if err := os.WriteFile(path, []byte("#!/bin/sh\nprintf 'codex-cli 1.2.3\\n'\nprintf ran > '"+marker+"'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	rows := DiscoverProfessionalAgents(context.Background())
	if _, err := os.Stat(marker); err != nil {
		t.Fatal("automatic discovery did not read the installed version")
	}
	for _, row := range rows {
		if row.Kind == "codex" && (!row.Installed || row.Authentication != "unknown" || row.Binary != path || row.Version != "codex-cli 1.2.3") {
			t.Fatal("installation was treated as sign-in")
		}
	}
	row, err := CheckProfessionalAgent(context.Background(), "codex")
	if err != nil || row.Version != "codex-cli 1.2.3" || row.VersionState != "available" || row.Authentication != "unknown" {
		t.Fatalf("unexpected explicit check: %+v, %v", row, err)
	}
	if _, err := CheckProfessionalAgent(context.Background(), "codex;exit"); err == nil {
		t.Fatal("accepted an arbitrary command")
	}
}

func TestNativeOpenCodeDiscoveryAndVersionCheck(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PATH", t.TempDir())
	binDir := filepath.Join(home, ".opencode", "bin")
	if err := os.MkdirAll(binDir, 0700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(home, "version-ran")
	path := filepath.Join(binDir, "opencode")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n[ \"$#\" -eq 1 ] && [ \"$1\" = --version ] || exit 1\nprintf '1.2.3\\n'\nprintf ran > '"+marker+"'\n"), 0700); err != nil {
		t.Fatal(err)
	}
	row := discoverProfessionalAgent(context.Background(), "opencode")
	if !row.Installed || row.Binary != path || row.Authentication != "unknown" {
		t.Fatalf("native install not discovered: %+v", row)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("discovery executed OpenCode")
	}
	row, err := CheckProfessionalAgent(context.Background(), "opencode")
	if err != nil || row.Version != "1.2.3" || row.VersionState != "available" || row.Binary != path {
		t.Fatalf("native version check: %+v, %v", row, err)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatal("explicit version check did not execute OpenCode")
	}
}

func TestVersionProbeIsBoundedAndKeepsMissingToolsDistinct(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "slow")
	if err := os.WriteFile(path, []byte("#!/bin/sh\nexec /bin/sleep 10\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	started := time.Now()
	if version := probeProfessionalVersion(ctx, path); version != "" || time.Since(started) > time.Second {
		t.Fatal("version probe did not respect cancellation")
	}
	t.Setenv("PATH", dir)
	row, err := CheckProfessionalAgent(context.Background(), "codex")
	if err != nil || row.Installed || row.Version != "" {
		t.Fatalf("missing tool: %+v, %v", row, err)
	}
	output := &versionOutput{}
	_, _ = output.Write(make([]byte, 10000))
	if len(output.text) != 4096 {
		t.Fatal("version output was not bounded")
	}
}
