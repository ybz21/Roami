package agentexecution

import (
	"github.com/ybz21/Roami/internal/agentlifecycle"
	"os"
	"path/filepath"
)

func sessionHostProof() string                      { return agentlifecycle.HostProof() }
func sessionDirectoryProof(directory string) string { return agentlifecycle.DirectoryProof(directory) }

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
