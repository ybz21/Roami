//go:build !windows

// Package fsguard provides cross-platform file ownership, inode identity, and symlink-safe open primitives.
package fsguard

import (
	"os"
	"syscall"

	"golang.org/x/sys/unix"
)

func OwnedByCurrentUser(info os.FileInfo) bool {
	if info == nil {
		return false
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	return ok && int(st.Uid) == os.Geteuid()
}

func FileIdentity(info os.FileInfo) (dev, ino uint64, ok bool) {
	if info == nil {
		return 0, 0, false
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return 0, 0, false
	}
	return uint64(st.Dev), uint64(st.Ino), true
}

func OpenNoFollow(path string, create, cloexec bool, perm uint32) (*os.File, error) {
	flags := unix.O_RDWR | unix.O_NOFOLLOW
	if create {
		flags |= unix.O_CREAT
	}
	if cloexec {
		flags |= unix.O_CLOEXEC
	}
	fd, err := unix.Open(path, flags, perm)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), path), nil
}

func OpenRootReadNoFollow(root *os.Root, name string) (*os.File, error) {
	return root.OpenFile(name, os.O_RDONLY|unix.O_NOFOLLOW|unix.O_NONBLOCK, 0)
}

func OpenReadNoFollow(path string) (*os.File, error) {
	fd, err := unix.Open(path, unix.O_RDONLY|unix.O_NOFOLLOW|unix.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), path), nil
}
