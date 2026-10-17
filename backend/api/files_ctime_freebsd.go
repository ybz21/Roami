package api

import (
	"os"
	"syscall"
)

func fileCtime(info os.FileInfo) int64 {
	if st, ok := info.Sys().(*syscall.Stat_t); ok {
		return st.Birthtimespec.Sec
	}
	return info.ModTime().Unix()
}
