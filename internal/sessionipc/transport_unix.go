//go:build linux || darwin

package sessionipc

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net"
	"os"
	"path/filepath"
)

const maxUnixSocketPath = 90 // Safely below macOS sun_path limit of 104 bytes.

// ListenLocal creates a private 0600 Unix domain socket whose path is guaranteed <= 90 bytes.
func ListenLocal(instanceRoot, hostID string) (net.Listener, string, string, error) {
	sum := sha256.Sum256([]byte(instanceRoot + "\x00" + hostID))
	short := hex.EncodeToString(sum[:6]) // 12 hex chars
	name := "rs-" + short + ".sock"

	candidateDir := filepath.Join(instanceRoot, "run")
	sockPath := filepath.Join(candidateDir, name)
	if len(sockPath) > maxUnixSocketPath {
		candidateDir = filepath.Join("/tmp", fmt.Sprintf("roami-%d", os.Getuid()))
		sockPath = filepath.Join(candidateDir, name)
	}
	if err := os.MkdirAll(candidateDir, 0700); err != nil {
		return nil, "", "", err
	}
	_ = os.Chmod(candidateDir, 0700)
	_ = os.Remove(sockPath)

	ln, err := net.Listen("unix", sockPath)
	if err != nil {
		return nil, "", "", err
	}
	if err := os.Chmod(sockPath, 0600); err != nil {
		_ = ln.Close()
		_ = os.Remove(sockPath)
		return nil, "", "", err
	}
	return ln, "unix", sockPath, nil
}
