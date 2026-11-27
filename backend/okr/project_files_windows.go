//go:build windows

package okr

import (
	"os"
	"path/filepath"
	"strings"
)

func openNoFollowRead(root *os.Root, name string) (*os.File, error) {
	return root.OpenFile(name, os.O_RDONLY, 0)
}

func openNoFollowCreateExcl(root *os.Root, name string) (*os.File, error) {
	return root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
}

func openNoFollowLock(root *os.Root, name string) (*os.File, error) {
	return root.OpenFile(name, os.O_CREATE|os.O_RDWR, 0600)
}

func renameInDir(directory *os.Root, oldName, newName string) error {
	if strings.ContainsAny(oldName, `/\`) || strings.ContainsAny(newName, `/\`) {
		return ErrInvalid
	}
	base := directory.Name()
	return os.Rename(filepath.Join(base, oldName), filepath.Join(base, newName))
}
