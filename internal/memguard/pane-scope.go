package memguard

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// A pane can still share its tmux server's scope while systemd moves it.
func memoryScope(pid int) (string, error) {
	status, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/status")
	if err != nil {
		return "", err
	}
	parent := 0
	for _, line := range strings.Split(string(status), "\n") {
		if value, ok := strings.CutPrefix(line, "PPid:"); ok {
			parent, _ = strconv.Atoi(strings.TrimSpace(value))
			break
		}
	}
	scope := cgroupPath(pid)
	if err := validateMemoryScope(scope, cgroupPath(os.Getpid()), cgroupPath(parent)); err != nil {
		return "", err
	}
	return filepath.Base(scope), nil
}

func validateMemoryScope(scope, controller, parent string) error {
	unit := filepath.Base(scope)
	if !filepath.IsAbs(scope) || filepath.Clean(scope) != scope || !strings.HasPrefix(unit, "tmux-spawn-") || !strings.HasSuffix(unit, ".scope") {
		return fmt.Errorf("memguard: dedicated pane scope unavailable")
	}
	if controller == "" || parent == "" {
		return fmt.Errorf("memguard: cannot verify pane scope isolation")
	}
	for _, protected := range []string{controller, parent} {
		if protected == scope || strings.HasPrefix(protected, scope+"/") {
			return fmt.Errorf("memguard: refusing memory limits on controller or parent scope")
		}
	}
	return nil
}
