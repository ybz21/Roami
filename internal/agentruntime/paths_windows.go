//go:build windows

package agentruntime

import (
	"fmt"
	"os"
	"path/filepath"
)

func fallbackSocketDir() (string, error) {
	root := filepath.Join(os.TempDir(), "roami-agent")
	if err := os.MkdirAll(root, 0700); err != nil {
		return "", err
	}
	info, err := os.Lstat(root)
	if err != nil {
		return "", err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", fmt.Errorf("AGENT_SOCKET_DIRECTORY_UNSAFE")
	}
	return root, nil
}
