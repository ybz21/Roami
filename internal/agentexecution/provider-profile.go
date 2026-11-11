package agentexecution

import (
	"fmt"
	"os"
)

func providerHomeKey(executor string) string {
	if executor == "claude" {
		return "CLAUDE_CONFIG_DIR"
	}
	return "CODEX_HOME"
}

func restoreProviderHome(executor string, binding SessionBinding) error {
	key := providerHomeKey(executor)
	var err error
	if binding.ProviderHomeExplicit != nil && !*binding.ProviderHomeExplicit {
		// Claude's default ~/.claude uses ~/.claude.json; an explicit directory does not.
		err = os.Unsetenv(key)
	} else {
		// Old receipts lack the mode; preserve their existing recovery behavior.
		err = os.Setenv(key, binding.ProviderHome)
	}
	if err != nil {
		return err
	}
	if providerHome(executor) != binding.ProviderHome {
		return fmt.Errorf("SESSION_RECOVERY_PROFILE_CHANGED")
	}
	return nil
}
