//go:build darwin || freebsd || openbsd || netbsd

package ttyraw

import "golang.org/x/sys/unix"

const (
	ioctlReadTermios  = unix.TIOCGETA
	ioctlWriteTermios = unix.TIOCSETA
)
