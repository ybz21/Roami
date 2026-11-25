//go:build !windows

package pty

import (
	"os"
	"os/exec"

	creackpty "github.com/creack/pty"
)

type tmuxAttachSize struct {
	Rows uint16
	Cols uint16
}

func startTmuxAttachPTY(cmd *exec.Cmd, sz tmuxAttachSize) (*os.File, error) {
	return creackpty.StartWithSize(cmd, &creackpty.Winsize{Rows: sz.Rows, Cols: sz.Cols})
}

func resizeTmuxAttachPTY(ptmx *os.File, sz tmuxAttachSize) error {
	return creackpty.Setsize(ptmx, &creackpty.Winsize{Rows: sz.Rows, Cols: sz.Cols})
}
