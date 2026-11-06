package agentlifecycle

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"strings"
	"syscall"
)

// Local process evidence cannot travel with a copied database or another boot/namespace.
func HostProof() string {
	var parts []string
	for _, path := range []string{"/etc/machine-id", "/proc/sys/kernel/random/boot_id"} {
		value, err := os.ReadFile(path)
		if err != nil || strings.TrimSpace(string(value)) == "" {
			return ""
		}
		parts = append(parts, strings.TrimSpace(string(value)))
	}
	for _, namespace := range []string{"pid", "cgroup", "mnt"} {
		info, err := os.Stat("/proc/self/ns/" + namespace)
		if err != nil {
			return ""
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok {
			return ""
		}
		parts = append(parts, fmt.Sprintf("%s:%d:%d", namespace, stat.Dev, stat.Ino))
	}
	return identityHash(strings.Join(parts, "\x00"))
}

func DirectoryProof(directory string) string {
	info, err := os.Stat(directory)
	if err != nil || !info.IsDir() {
		return ""
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return ""
	}
	return identityHash(fmt.Sprintf("%s\x00%d:%d", directory, stat.Dev, stat.Ino))
}

func identityHash(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}
