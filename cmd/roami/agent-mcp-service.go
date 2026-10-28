package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func mcpSocketPath(paths agentruntime.Paths) string {
	if value := os.Getenv("ROAMI_MCP_SOCKET"); value != "" {
		return value
	}
	return filepath.Join(filepath.Dir(paths.Socket), strings.Replace(filepath.Base(paths.Socket), "agent-", "mcp-", 1))
}

func mcpUnitQuote(value string) string {
	return `"` + strings.NewReplacer(`\`, `\\`, `"`, `\"`, "%", "%%").Replace(value) + `"`
}

func writeMCPFile(path string, content []byte, mode os.FileMode) error {
	file, err := os.CreateTemp(filepath.Dir(path), ".mcp-")
	if err != nil {
		return err
	}
	temporary := file.Name()
	defer os.Remove(temporary)
	if err = file.Chmod(mode); err == nil {
		_, err = file.Write(content)
	}
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(temporary, path)
}

func installMCPService(dir string, paths agentruntime.Paths, socketPath string) error {
	if _, err := exec.LookPath("systemctl"); err != nil {
		return fmt.Errorf("MCP_SERVICE_MANAGER_UNAVAILABLE: use roami agent mcp serve with your service manager")
	}
	binary, err := os.Executable()
	if err != nil {
		return err
	}
	binary, err = filepath.EvalSymlinks(binary)
	if err != nil {
		return err
	}
	for _, value := range []string{binary, dir, paths.Storage.Home, paths.Storage.Data, socketPath} {
		if strings.ContainsAny(value, "\n\r\x00") {
			return fmt.Errorf("MCP_SERVICE_PATH_INVALID")
		}
	}
	unit := "roami-" + strings.TrimSuffix(filepath.Base(socketPath), ".sock") + ".service"
	if strings.ContainsAny(unit, "/\n\r\x00") {
		return fmt.Errorf("MCP_SERVICE_PATH_INVALID")
	}
	private := filepath.Join(paths.Storage.Data, "agents")
	if err = os.MkdirAll(private, 0700); err != nil {
		return err
	}
	info, err := os.Lstat(private)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return fmt.Errorf("MCP_PRIVATE_DIRECTORY_REQUIRED")
	}
	environment := map[string]string{}
	for _, value := range agentEnvironment() {
		key, entry, ok := strings.Cut(value, "=")
		if ok {
			environment[key] = entry
		}
	}
	environment["ROAMI_HOME"] = paths.Storage.Home
	environment["ROAMI_DATA"] = paths.Storage.Data
	environment["ROAMI_DATABASE_DIR"] = paths.Storage.Database
	environment["ROAMI_BACKUP_DIR"] = paths.Storage.Backup
	environment["ROAMI_CONFIG"] = filepath.Join(paths.Storage.Home, "config.yaml")
	environment["ROAMI_AGENT_RUNTIME"] = dir
	environment["ROAMI_MCP_SOCKET"] = socketPath
	var keys []string
	for key := range environment {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	var lines []string
	validName := regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)
	for _, key := range keys {
		if !validName.MatchString(key) || strings.ContainsRune(environment[key], 0) {
			continue
		}
		value := strings.NewReplacer(`\`, `\\`, `"`, `\"`).Replace(environment[key])
		lines = append(lines, key+`="`+value+`"`)
	}
	envPath := filepath.Join(private, "mcp-daemon.env")
	if err = writeMCPFile(envPath, []byte(strings.Join(lines, "\n")+"\n"), 0600); err != nil {
		return err
	}
	unitRoot := os.Getenv("XDG_CONFIG_HOME")
	if unitRoot == "" {
		unitRoot = filepath.Join(os.Getenv("HOME"), ".config")
	}
	unitDir := filepath.Join(unitRoot, "systemd", "user")
	if err = os.MkdirAll(unitDir, 0700); err != nil {
		return err
	}
	content := "[Unit]\nDescription=Roami independent MCP connections\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nEnvironmentFile=" + strings.ReplaceAll(envPath, "%", "%%") + "\nExecStart=" + mcpUnitQuote(binary) + " agent mcp serve --runtime-dir " + mcpUnitQuote(dir) + " --home-root " + mcpUnitQuote(paths.Storage.Home) + " --data-root " + mcpUnitQuote(paths.Storage.Data) + " --socket " + mcpUnitQuote(socketPath) + "\nRestart=always\nRestartSec=2\nKillMode=control-group\nTimeoutStopSec=15\n\n[Install]\nWantedBy=default.target\n"
	if err = writeMCPFile(filepath.Join(unitDir, unit), []byte(content), 0600); err != nil {
		return err
	}
	for _, args := range [][]string{{"--user", "daemon-reload"}, {"--user", "enable", "--now", unit}} {
		cmd := exec.Command("systemctl", args...)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err = cmd.Run(); err != nil {
			return err
		}
	}
	ready := false
	for attempt := 0; attempt < 80; attempt++ {
		if mcpDaemonReady(socketPath, paths.Storage.Data) {
			ready = true
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !ready {
		return fmt.Errorf("MCP_DAEMON_START_TIMEOUT")
	}
	descriptor, _ := json.Marshal(map[string]any{"version": 1, "socket": socketPath, "unit": unit})
	if err = writeMCPFile(filepath.Join(private, "mcp-daemon.json"), descriptor, 0600); err != nil {
		return err
	}
	fmt.Println("MCP daemon enabled:", unit)
	return nil
}
