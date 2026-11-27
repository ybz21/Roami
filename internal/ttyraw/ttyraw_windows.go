//go:build windows

// Package ttyraw provides cross-platform local terminal raw mode and resize notifications.
package ttyraw

import (
	"context"
	"sync"
	"time"

	"golang.org/x/sys/windows"
)

func IsTerminal(fd uintptr) bool {
	var mode uint32
	return windows.GetConsoleMode(windows.Handle(fd), &mode) == nil
}

func MakeRaw(fd uintptr) (func(), error) {
	inHandle := windows.Handle(fd)
	var oldIn uint32
	if err := windows.GetConsoleMode(inHandle, &oldIn); err != nil {
		return func() {}, err
	}
	rawIn := oldIn
	rawIn &^= windows.ENABLE_ECHO_INPUT | windows.ENABLE_PROCESSED_INPUT | windows.ENABLE_LINE_INPUT | windows.ENABLE_PROCESSED_OUTPUT
	rawIn |= windows.ENABLE_VIRTUAL_TERMINAL_INPUT
	if err := windows.SetConsoleMode(inHandle, rawIn); err != nil {
		return func() {}, err
	}

	outHandle, outErr := windows.GetStdHandle(windows.STD_OUTPUT_HANDLE)
	var oldOut uint32
	hasOut := outErr == nil && windows.GetConsoleMode(outHandle, &oldOut) == nil
	if hasOut {
		rawOut := oldOut | windows.ENABLE_VIRTUAL_TERMINAL_PROCESSING | windows.DISABLE_NEWLINE_AUTO_RETURN
		_ = windows.SetConsoleMode(outHandle, rawOut)
	}

	var once sync.Once
	restore := func() {
		once.Do(func() {
			_ = windows.SetConsoleMode(inHandle, oldIn)
			if hasOut {
				_ = windows.SetConsoleMode(outHandle, oldOut)
			}
		})
	}
	return restore, nil
}

func Size(fd uintptr) (cols, rows uint16, err error) {
	handle, err := windows.GetStdHandle(windows.STD_OUTPUT_HANDLE)
	if err != nil {
		handle = windows.Handle(fd)
	}
	var info windows.ConsoleScreenBufferInfo
	if err := windows.GetConsoleScreenBufferInfo(handle, &info); err != nil {
		return 0, 0, err
	}
	w := info.Window.Right - info.Window.Left + 1
	h := info.Window.Bottom - info.Window.Top + 1
	if w <= 0 || h <= 0 {
		return 80, 24, nil
	}
	return uint16(w), uint16(h), nil
}

func WatchResize(ctx context.Context, fd uintptr, onResize func(cols, rows uint16)) {
	ticker := time.NewTicker(150 * time.Millisecond)
	defer ticker.Stop()

	lastCols, lastRows, _ := Size(fd)
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
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
