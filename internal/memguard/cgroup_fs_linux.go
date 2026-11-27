//go:build linux

package memguard

import "syscall"

func isCgroup2Filesystem(root string) bool {
	var filesystem syscall.Statfs_t
	return syscall.Statfs(root, &filesystem) == nil && filesystem.Type == 0x63677270
}
