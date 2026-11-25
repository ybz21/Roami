//go:build !windows

// Package ttyraw provides cross-platform local terminal raw mode and resize notifications.
package ttyraw

import (
	"context"
	"os"
	"os/signal"
	"sync"
	"syscall"

	"golang.org/x/sys/unix"
)

func IsTerminal(fd uintptr) bool {
	_, err := unix.IoctlGetTermios(int(fd), ioctlReadTermios)
	return err == nil
}

func MakeRaw(fd uintptr) (func(), error) {
	oldState, err := unix.IoctlGetTermios(int(fd), ioctlReadTermios)
	if err != nil {
		return func() {}, err
	}
	raw := *oldState
	raw.Iflag &^= unix.IGNBRK | unix.BRKINT | unix.PARMRK | unix.ISTRIP | unix.INLCR | unix.IGNCR | unix.ICRNL | unix.IXON
	raw.Oflag &^= unix.OPOST
	raw.Lflag &^= unix.ECHO | unix.ECHONL | unix.ICANON | unix.ISIG | unix.IEXTEN
	raw.Cflag &^= unix.CSIZE | unix.PARENB
	raw.Cflag |= unix.CS8
	raw.Cc[unix.VMIN] = 1
	raw.Cc[unix.VTIME] = 0

	if err := unix.IoctlSetTermios(int(fd), ioctlWriteTermios, &raw); err != nil {
		return func() {}, err
	}
	var once sync.Once
	restore := func() {
		once.Do(func() {
			_ = unix.IoctlSetTermios(int(fd), ioctlWriteTermios, oldState)
		})
	}
	return restore, nil
}

func Size(fd uintptr) (cols, rows uint16, err error) {
	ws, err := unix.IoctlGetWinsize(int(fd), unix.TIOCGWINSZ)
	if err != nil {
		return 0, 0, err
	}
	return ws.Col, ws.Row, nil
}

func WatchResize(ctx context.Context, fd uintptr, onResize func(cols, rows uint16)) {
	sigCh := make(chan os.Signal, 4)
	signal.Notify(sigCh, syscall.SIGWINCH)
	defer signal.Stop(sigCh)

	var lastCols, lastRows uint16
	for {
		select {
		case <-ctx.Done():
			return
		case <-sigCh:
			cols, rows, err := Size(fd)
			if err != nil || cols == 0 || rows == 0 {
				continue
			}
			if cols == lastCols && rows == lastRows {
				continue
			}
			lastCols, lastRows = cols, rows
			onResize(cols, rows)
		}
	}
}
