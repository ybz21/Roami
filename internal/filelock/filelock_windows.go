//go:build windows

package filelock

import (
	"errors"
	"os"

	"golang.org/x/sys/windows"
)

func lockFile(f *os.File, shared, nonblocking bool) (func() error, error) {
	var flags uint32
	if !shared {
		flags |= windows.LOCKFILE_EXCLUSIVE_LOCK
	}
	if nonblocking {
		flags |= windows.LOCKFILE_FAIL_IMMEDIATELY
	}
	var ol windows.Overlapped
	// Lock the same fixed 1-byte range across all processes to mirror flock semantics.
	if err := windows.LockFileEx(windows.Handle(f.Fd()), flags, 0, 1, 0, &ol); err != nil {
		if errors.Is(err, windows.ERROR_LOCK_VIOLATION) {
			return nil, ErrWouldBlock
		}
		return nil, err
	}
	return func() error {
		var uol windows.Overlapped
		return windows.UnlockFileEx(windows.Handle(f.Fd()), 0, 1, 0, &uol)
	}, nil
}
