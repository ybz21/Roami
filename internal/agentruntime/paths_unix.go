//go:build !windows

package agentruntime

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
)

func fallbackSocketDir() (string, error) {
	root := filepath.Join("/tmp", fmt.Sprintf("roami-agent-%d", os.Geteuid()))
	if err := os.Mkdir(root, 0700); err != nil && !os.IsExist(err) {
		return "", err
	}
	info, err := os.Lstat(root)
	if err != nil {
		return "", err
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !info.IsDir() || info.Mode().Perm() != 0700 || !ok || int(st.Uid) != os.Geteuid() {
		return "", fmt.Errorf("AGENT_SOCKET_DIRECTORY_UNSAFE")
	}
	return root, nil
}
