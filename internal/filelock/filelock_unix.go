//go:build !windows

package filelock

import (
	"errors"
	"os"
	"syscall"

	"golang.org/x/sys/unix"
)

func lockFile(f *os.File, shared, nonblocking bool) (func() error, error) {
	how := unix.LOCK_EX
	if shared {
		how = unix.LOCK_SH
	}
	if nonblocking {
		how |= unix.LOCK_NB
	}
	if err := unix.Flock(int(f.Fd()), how); err != nil {
		if errors.Is(err, syscall.EWOULDBLOCK) || errors.Is(err, syscall.EAGAIN) {
			return nil, ErrWouldBlock
		}
		return nil, err
	}
	return func() error { return unix.Flock(int(f.Fd()), unix.LOCK_UN) }, nil
}
