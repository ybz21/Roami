//go:build !windows

package okr

import (
	"os"

	"golang.org/x/sys/unix"
)

func openNoFollowRead(root *os.Root, name string) (*os.File, error) {
	return root.OpenFile(name, os.O_RDONLY|unix.O_NOFOLLOW|unix.O_NONBLOCK, 0)
}

func openNoFollowCreateExcl(root *os.Root, name string) (*os.File, error) {
	return root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL|unix.O_NOFOLLOW, 0600)
}

func openNoFollowLock(root *os.Root, name string) (*os.File, error) {
	return root.OpenFile(name, os.O_CREATE|os.O_RDWR|unix.O_NOFOLLOW, 0600)
}

func renameInDir(directory *os.Root, oldName, newName string) error {
	dir, err := directory.Open(".")
	if err != nil {
		return err
	}
	defer dir.Close()
	if err := unix.Renameat(int(dir.Fd()), oldName, int(dir.Fd()), newName); err != nil {
		return err
	}
	return dir.Sync()
}
