package httpapi

import (
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

func Socket(agentSocket string) string {
	return filepath.Join(filepath.Dir(agentSocket), "model-"+strings.TrimPrefix(filepath.Base(agentSocket), "agent-"))
}

// The lock survives socket unlinking and prevents two supervisors recovering each other's calls.
func ListenManagement(socket string) (net.Listener, func(), error) {
	if err := os.MkdirAll(filepath.Dir(socket), 0700); err != nil {
		return nil, nil, err
	}
	fd, err := unix.Open(socket+".lock", unix.O_CREAT|unix.O_RDWR|unix.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, nil, err
	}
	locked := false
	defer func() {
		if !locked {
			unix.Close(fd)
		}
	}()
	if err = unix.Flock(fd, unix.LOCK_EX|unix.LOCK_NB); err != nil {
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
		_ = unix.Flock(fd, unix.LOCK_UN)
		_ = unix.Close(fd)
	}, nil
}

func AgentSocket(modelSocket string) string {
	return filepath.Join(filepath.Dir(modelSocket), "agent-"+strings.TrimPrefix(filepath.Base(modelSocket), "model-"))
}
