package agent

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

// ResolveBinary keeps discovery and launches consistent when a service lacks shell PATH additions.
func ResolveBinary(kind string) (string, error) {
	a := Get(kind)
	if a == nil {
		return "", fmt.Errorf("unknown agent kind: %s", kind)
	}
	path, err := exec.LookPath(a.Bin())
	if err == nil {
		return path, nil
	}
	if a.Kind() == "opencode" {
		if home, homeErr := os.UserHomeDir(); homeErr == nil && filepath.IsAbs(home) {
			if path, fallbackErr := exec.LookPath(filepath.Join(home, ".opencode", "bin", a.Bin())); fallbackErr == nil {
				return path, nil
			}
		}
	}
	return "", err
}
