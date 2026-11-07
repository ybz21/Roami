package memguard

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// FreezeState reads the kernel's completed state, not just a requested freeze.
func FreezeState(pid int) (bool, error) {
	dir, err := freezeDirectory(pid)
	if err != nil {
		return false, err
	}
	n, ok := statField(filepath.Join(dir, "cgroup.events"), "frozen")
	if !ok {
		return false, fmt.Errorf("session freezer unavailable")
	}
	return n == 1, nil
}

func freezeDirectory(pid int) (string, error) {
	if _, err := memoryScope(pid); err != nil {
		return "", err
	}
	dir := cgroupDir(pid)
	base := filepath.Base(dir)
	if dir == "" || !strings.HasPrefix(base, "tmux-spawn-") || !strings.HasSuffix(base, ".scope") {
		return "", fmt.Errorf("dedicated pane scope unavailable")
	}
	// A controller must never freeze itself or a shared user/service cgroup.
	self := cgroupDir(os.Getpid())
	if self == dir || strings.HasPrefix(self, dir+"/") {
		return "", fmt.Errorf("cannot freeze controller scope")
	}
	return dir, nil
}

// Freeze stops all descendants, including detached children, without ending the pane.
func Freeze(pid int, frozen bool) error {
	dir, err := freezeDirectory(pid)
	if err != nil {
		return err
	}
	value := "0"
	if frozen {
		value = "1"
	}
	if err := os.WriteFile(filepath.Join(dir, "cgroup.freeze"), []byte(value), 0); err != nil {
		return err
	}
	deadline := time.Now().Add(500 * time.Millisecond)
	for {
		got, err := FreezeState(pid)
		if err != nil {
			return err
		}
		if got == frozen {
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("session freezer transition pending")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// Pressure reads the host and user slice PSI; oomd may monitor the latter.
func Pressure() float64 {
	pressure := pressureFile("/proc/pressure/memory")
	for dir := cgroupDir(os.Getpid()); dir != "" && dir != "/sys/fs/cgroup" && dir != "/"; dir = filepath.Dir(dir) {
		if p := pressureFile(filepath.Join(dir, "memory.pressure")); p > pressure {
			pressure = p
		}
	}
	return pressure
}

func pressureFile(path string) float64 {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "some ") {
			var p float64
			if _, err := fmt.Sscanf(line, "some avg10=%f", &p); err == nil {
				return p
			}
		}
	}
	return 0
}
