//go:build linux

package terminal

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// ProcessIdentity returns a PID-reuse-safe start-time token from /proc/<pid>/stat.
func (UnixBackend) ProcessIdentity(pid int) (string, error) {
	if pid < 1 {
		return "", fmt.Errorf("terminal: invalid pid %d", pid)
	}
	raw, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
	if err != nil {
		return "", err
	}
	end := strings.LastIndexByte(string(raw), ')')
	if end < 0 {
		return "", fmt.Errorf("terminal: malformed /proc/%d/stat", pid)
	}
	fields := strings.Fields(string(raw[end+1:]))
	if len(fields) < 20 {
		return "", fmt.Errorf("terminal: incomplete /proc/%d/stat", pid)
	}
	return fmt.Sprintf("linux:%d:%s", pid, fields[19]), nil
}

// CurrentDir resolves the process's current working directory via /proc/<pid>/cwd.
func (UnixBackend) CurrentDir(pid int) (string, error) {
	if pid < 1 {
		return "", fmt.Errorf("terminal: invalid pid %d", pid)
	}
	return os.Readlink(filepath.Join("/proc", strconv.Itoa(pid), "cwd"))
}
