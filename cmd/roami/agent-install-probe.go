package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/agentruntime"
)

// This command always uses disposable storage and never reads a user's model configuration.
func runAgentInstallProbe(args []string) int {
	fs := flag.NewFlagSet("agent install-probe", flag.ContinueOnError)
	dir := fs.String("runtime-dir", "", "prepared runtime directory")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *dir == "" || fs.NArg() != 0 {
		return 2
	}
	if err := probeAgentInstallation(*dir); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	fmt.Println("Agent installation probe passed: settings read, write and restart")
	return 0
}

func probeAgentInstallation(dir string) error {
	root, err := os.MkdirTemp("/tmp", "roami-install-probe-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(root)
	for _, value := range os.Environ() {
		key, _, _ := strings.Cut(value, "=")
		if strings.HasPrefix(key, "ROAMI_") || strings.HasPrefix(key, "ROAM_") || strings.HasPrefix(key, "TTMUX_") {
			os.Unsetenv(key)
		}
	}
	for key, value := range map[string]string{"ROAMI_HOME": root, "ROAMI_DATA": root, "ROAMI_CONFIG": filepath.Join(root, "config.yaml"), "ROAMI_AGENT_RUNTIME": dir} {
		if err := os.Setenv(key, value); err != nil {
			return err
		}
	}
	if err := initializeAgent(dir); err != nil {
		return err
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		return err
	}
	stop, err := startAgentSupervisor()
	if err != nil {
		return err
	}
	defer func() { stop() }()
	data, err := agentRequest(paths.Socket, "GET", "/v1/model-settings", nil)
	if err != nil {
		return err
	}
	var initial struct {
		Data struct {
			Connection struct {
				BaseURL       string `json:"baseUrl"`
				KeyConfigured bool   `json:"keyConfigured"`
			} `json:"connection"`
		} `json:"data"`
	}
	if err := json.Unmarshal(data, &initial); err != nil {
		return err
	}
	if initial.Data.Connection.BaseURL != "" || initial.Data.Connection.KeyConfigured {
		return fmt.Errorf("INSTALL_PROBE_NOT_ISOLATED")
	}
	fixture := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"data":[{"id":"installation-probe","context_window":8192}]}`)
	}))
	defer fixture.Close()
	role := map[string]any{"model": "installation-probe", "images": false, "contextWindow": 8192}
	patch := map[string]any{"connection": map[string]string{"baseUrl": fixture.URL}, "main": role, "worker": role}
	if _, err = agentRequest(paths.Socket, "PUT", "/v1/model-settings", patch); err != nil {
		return err
	}
	stop()
	stop, err = startAgentSupervisor()
	if err != nil {
		stop = func() {}
		return err
	}
	data, err = agentRequest(paths.Socket, "GET", "/v1/model-settings", nil)
	if err != nil {
		return err
	}
	if !strings.Contains(string(data), "installation-probe") {
		return fmt.Errorf("INSTALL_PROBE_SETTINGS_LOST")
	}
	return nil
}
