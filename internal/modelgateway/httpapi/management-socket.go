package httpapi

import (
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/filelock"
	"github.com/ybz21/Roami/internal/fsguard"
)

func Socket(agentSocket string) string {
	return filepath.Join(filepath.Dir(agentSocket), "model-"+strings.TrimPrefix(filepath.Base(agentSocket), "agent-"))
}

// The lock survives socket unlinking and prevents two supervisors recovering each other's calls.
func ListenManagement(socket string) (net.Listener, func(), error) {
	if err := os.MkdirAll(filepath.Dir(socket), 0700); err != nil {
		return nil, nil, err
	}
	lockFile, err := fsguard.OpenNoFollow(socket+".lock", true, false, 0600)
	if err != nil {
		return nil, nil, err
	}
	var unlockLock func() error
	locked := false
	defer func() {
		if !locked {
			if unlockLock != nil {
				_ = unlockLock()
			}
			_ = lockFile.Close()
		}
	}()
	unlockLock, err = filelock.Lock(lockFile, false, true)
	if err != nil {
		return nil, nil, fmt.Errorf("MODEL_GATEWAY_ALREADY_RUNNING: %w", err)
	}
	if info, err := os.Lstat(socket); err == nil {
		if info.Mode()&os.ModeSocket == 0 {
			return nil, nil, fmt.Errorf("MODEL_GATEWAY_SOCKET_UNSAFE")
		}
		if err = os.Remove(socket); err != nil {
			return nil, nil, err
		}
	} else if !os.IsNotExist(err) {
		return nil, nil, err
	}
	listener, err := net.Listen("unix", socket)
	if err != nil {
		return nil, nil, err
	}
	if err = os.Chmod(socket, 0600); err != nil {
		listener.Close()
		return nil, nil, err
	}
	locked = true
	return listener, func() {
		_ = unlockLock()
		_ = lockFile.Close()
	}, nil
}

func AgentSocket(modelSocket string) string {
	return filepath.Join(filepath.Dir(modelSocket), "agent-"+strings.TrimPrefix(filepath.Base(modelSocket), "model-"))
}
