package main

import (
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/agentruntime"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func TestMCPInstallUsesIndependentPrivateNodeService(t *testing.T) {
	root, err := os.MkdirTemp("", "roami-mcp-install-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(root)
	t.Setenv("HOME", root)
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(root, "config"))
	t.Setenv("ROAMI_MCP_SOCKET", "")
	bin := filepath.Join(root, "bin")
	if err = os.MkdirAll(bin, 0700); err != nil {
		t.Fatal(err)
	}
	systemctl := filepath.Join(bin, "systemctl")
	if err = os.WriteFile(systemctl, []byte("#!/bin/sh\nexit 0\n"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("MCP_TEST_VALUE", `value with spaces $dollar "quote"`)
	run := filepath.Join(root, "run")
	if err = os.MkdirAll(run, 0700); err != nil {
		t.Fatal(err)
	}
	socket := filepath.Join(run, "mcp-test.sock")
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/state" {
			t.Errorf("unexpected path %s", r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"servers":{},"dataRoot":"` + root + `"}`))
	})}
	defer server.Close()
	go func() { _ = server.Serve(listener) }()
	paths := agentruntime.Paths{Socket: filepath.Join(run, "agent-test.sock"), Config: filepath.Join(root, "agent.toml"), Storage: metadb.Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}}
	if err = installMCPService(filepath.Join(root, "runtime"), paths, socket); err != nil {
		t.Fatal(err)
	}
	descriptor := filepath.Join(root, "agents/mcp-daemon.json")
	raw, err := os.ReadFile(descriptor)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(raw), "mcp-test.sock") {
		t.Fatalf("missing socket: %s", raw)
	}
	for _, name := range []string{"mcp-daemon.env", "mcp-daemon.json"} {
		info, e := os.Stat(filepath.Join(root, "agents", name))
		if e != nil || info.Mode().Perm() != 0600 {
			t.Fatalf("private %s: %v", name, e)
		}
	}
	unit, err := os.ReadFile(filepath.Join(root, "config/systemd/user/roami-mcp-test.service"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(unit)
	for _, unwanted := range []string{"PartOf=", "BindsTo=", "Requires=roami", "After=roami"} {
		if strings.Contains(text, unwanted) {
			t.Fatalf("coupled lifecycle: %s", text)
		}
	}
	if !strings.Contains(text, "Restart=always") || !strings.Contains(text, "agent mcp serve") {
		t.Fatalf("missing supervision: %s", text)
	}
	if strings.Contains(text, "$dollar") {
		t.Fatal("environment secret entered service unit")
	}
	environment, err := os.ReadFile(filepath.Join(root, "agents/mcp-daemon.env"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(environment), `MCP_TEST_VALUE="value with spaces $dollar \"quote\""`) {
		t.Fatal("environment quoting lost data")
	}
}

func TestMCPUnitArgumentsEscapeSpecifierExpansion(t *testing.T) {
	if got := mcpUnitQuote(`/tmp/a b%"c`); got != `"/tmp/a b%%\"c"` {
		t.Fatalf("unexpected unit quote %s", got)
	}
}
