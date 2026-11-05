package agentexecution

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

// Local process evidence cannot travel with a copied database or another boot/namespace.
func sessionHostProof() string {
	var parts []string
	for _, path := range []string{"/etc/machine-id", "/proc/sys/kernel/random/boot_id"} {
		value, err := os.ReadFile(path)
		if err != nil || strings.TrimSpace(string(value)) == "" {
			return ""
		}
		parts = append(parts, strings.TrimSpace(string(value)))
	}
	for _, namespace := range []string{"pid", "cgroup", "mnt"} {
		info, err := os.Stat("/proc/self/ns/" + namespace)
		if err != nil {
			return ""
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok {
			return ""
		}
		parts = append(parts, fmt.Sprintf("%s:%d:%d", namespace, stat.Dev, stat.Ino))
	}
	return workspaceHash(strings.Join(parts, "\x00"))
}

func sessionDirectoryProof(directory string) string {
	info, err := os.Stat(directory)
	if err != nil || !info.IsDir() {
		return ""
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return ""
	}
	return workspaceHash(fmt.Sprintf("%s\x00%d:%d", directory, stat.Dev, stat.Ino))
}

func providerHome(executor string) string {
	key, fallback := "CODEX_HOME", ".codex"
	if executor == "claude" {
		key, fallback = "CLAUDE_CONFIG_DIR", ".claude"
	}
	home := os.Getenv(key)
	if home == "" {
		user, err := os.UserHomeDir()
		if err != nil {
			return ""
		}
		home = filepath.Join(user, fallback)
	}
	canonical, err := canonicalWorkspace(home)
	if err != nil {
		return ""
	}
	return canonical
}
