//go:build !linux

package memguard

func isCgroup2Filesystem(_ string) bool { return false }
