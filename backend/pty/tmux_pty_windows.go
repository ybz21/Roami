//go:build windows

package pty

import (
	"errors"
	"os"
	"os/exec"
)

type tmuxAttachSize struct {
	Rows uint16
	Cols uint16
}

func startTmuxAttachPTY(_ *exec.Cmd, _ tmuxAttachSize) (*os.File, error) {
	return nil, errors.New("tmux attach is not supported on Windows; use native terminal")
}

func resizeTmuxAttachPTY(_ *os.File, _ tmuxAttachSize) error {
	return errors.New("tmux attach is not supported on Windows")
}
