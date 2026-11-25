//go:build windows

package api

import (
	"os"
	"syscall"
)

func fileCtime(info os.FileInfo) int64 {
	if data, ok := info.Sys().(*syscall.Win32FileAttributeData); ok {
		return data.CreationTime.Nanoseconds() / 1e9
	}
	return info.ModTime().Unix()
}
