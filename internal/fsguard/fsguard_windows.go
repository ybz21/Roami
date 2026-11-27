//go:build windows

// Package fsguard provides cross-platform file ownership, inode identity, and symlink-safe open primitives.
package fsguard

import (
	"errors"
	"os"
)

func OwnedByCurrentUser(info os.FileInfo) bool {
	return info != nil && info.Mode()&os.ModeSymlink == 0
}

func FileIdentity(_ os.FileInfo) (dev, ino uint64, ok bool) {
	return 0, 0, false
}

func OpenNoFollow(path string, create, _ bool, perm uint32) (*os.File, error) {
	if info, err := os.Lstat(path); err == nil {
		if info.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("symlink not allowed")
		}
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	flags := os.O_RDWR
	if create {
		flags |= os.O_CREATE
	}
	return os.OpenFile(path, flags, os.FileMode(perm))
}

func OpenRootReadNoFollow(root *os.Root, name string) (*os.File, error) {
	return root.OpenFile(name, os.O_RDONLY, 0)
}

func OpenReadNoFollow(path string) (*os.File, error) {
	if info, err := os.Lstat(path); err == nil {
		if info.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("symlink not allowed")
		}
	} else {
		return nil, err
	}
	return os.Open(path)
}
