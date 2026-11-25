// Package filelock provides cross-platform advisory file locking (Flock on Unix, LockFileEx on Windows).
package filelock

import (
	"errors"
	"os"
)

// ErrWouldBlock is returned when a non-blocking lock cannot be acquired immediately.
var ErrWouldBlock = errors.New("file lock busy")

// Lock acquires a shared or exclusive lock on f, returning an idempotent unlock function.
func Lock(f *os.File, shared, nonblocking bool) (func() error, error) {
	return lockFile(f, shared, nonblocking)
}
