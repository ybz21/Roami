package memguard

import (
	_ "embed"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

//go:embed zram-setup.sh
var CompressionSetup []byte

type CompressionStatus struct {
	Zram      bool  `json:"zram"`
	Zswap     bool  `json:"zswap"`
	SwapTotal int64 `json:"swapTotal"`
	SwapFree  int64 `json:"swapFree"`
	Original  int64 `json:"original"`
	Memory    int64 `json:"memory"`
	Saved     int64 `json:"saved"`
}

func Compression() CompressionStatus { return compressionStatus("/proc", "/sys") }

func compressionStatus(proc, sys string) CompressionStatus {
	var out CompressionStatus
	if b, err := os.ReadFile(filepath.Join(proc, "meminfo")); err == nil {
		for _, line := range strings.Split(string(b), "\n") {
			f := strings.Fields(line)
			if len(f) < 2 {
				continue
			}
			n, _ := strconv.ParseInt(f[1], 10, 64)
			switch f[0] {
			case "SwapTotal:":
				out.SwapTotal = n * 1024
			case "SwapFree:":
				out.SwapFree = n * 1024
			}
		}
	}
	if b, err := os.ReadFile(filepath.Join(sys, "module/zswap/parameters/enabled")); err == nil {
		out.Zswap = strings.EqualFold(strings.TrimSpace(string(b)), "Y")
	}
	b, _ := os.ReadFile(filepath.Join(proc, "swaps"))
	for _, line := range strings.Split(string(b), "\n") {
		f := strings.Fields(line)
		if len(f) < 5 || !strings.HasPrefix(f[0], "/dev/zram") {
			continue
		}
		out.Zram = true
		stat, err := os.ReadFile(filepath.Join(sys, "block", filepath.Base(f[0]), "mm_stat"))
		if err != nil {
			continue
		}
		v := strings.Fields(string(stat))
		if len(v) < 3 {
			continue
		}
		original, e1 := strconv.ParseInt(v[0], 10, 64)
		memory, e2 := strconv.ParseInt(v[2], 10, 64)
		if e1 == nil && e2 == nil && original >= 0 && memory >= 0 {
			out.Original += original
			out.Memory += memory
		}
	}
	if out.Original > out.Memory {
		out.Saved = out.Original - out.Memory
	}
	return out
}
