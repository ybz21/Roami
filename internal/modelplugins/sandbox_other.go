//go:build !linux

package modelplugins

import (
	"errors"
	"os/exec"
)

type SandboxPaths struct{ Bun, Runtime, Package, State, EgressSocket, Unit string }

func SandboxCommand(SandboxPaths) (*exec.Cmd, error) {
	return nil, errors.New("MODEL_PLUGIN_SANDBOX_UNAVAILABLE")
}
