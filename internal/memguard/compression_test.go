package memguard

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestCompressionMeasuresOnlyActiveDevicesAndIncludesOverhead(t *testing.T) {
	root := t.TempDir()
	proc := filepath.Join(root, "proc")
	sys := filepath.Join(root, "sys")
	write := func(path, value string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(value), 0600); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(proc, "meminfo"), "SwapTotal: 1024 kB\nSwapFree: 512 kB\n")
	write(filepath.Join(proc, "swaps"), "Filename Type Size Used Priority\n/dev/zram0 partition 100 40 100\n/swap.img file 100 50 -1\n")
	write(filepath.Join(sys, "block/zram0/mm_stat"), "1000 200 300 0 0 0\n")
	write(filepath.Join(sys, "block/zram1/mm_stat"), "9000 2000 3000\n")
	write(filepath.Join(sys, "module/zswap/parameters/enabled"), "N\n")
	s := compressionStatus(proc, sys)
	if !s.Zram || s.Zswap || s.Original != 1000 || s.Memory != 300 || s.Saved != 700 || s.SwapFree != 512*1024 {
		t.Fatalf("wrong compression evidence: %+v", s)
	}
	write(filepath.Join(proc, "swaps"), "Filename Type Size Used Priority\n/swap.img file 100 50 -1\n")
	s = compressionStatus(proc, sys)
	if s.Zram || s.Saved != 0 {
		t.Fatal("inactive devices reported as active")
	}
}

func TestSetupScriptValidatesBeforeChangingTheHost(t *testing.T) {
	path := filepath.Join(t.TempDir(), "setup.sh")
	if err := os.WriteFile(path, CompressionSetup, 0600); err != nil {
		t.Fatal(err)
	}
	out, err := exec.Command("bash", path, "16G", "--memory-limit", "4G", "--dry-run").CombinedOutput()
	if err != nil || !strings.Contains(string(out), "size=16G memory_limit=4G") {
		t.Fatalf("dry-run: %s %v", out, err)
	}
	for _, bad := range []string{"0G", "16G; touch bad", "-1G", "$(id)"} {
		if out, err := exec.Command("bash", path, bad, "--dry-run").CombinedOutput(); err == nil {
			t.Fatalf("accepted %q: %s", bad, out)
		}
	}
}

func TestReclaimNeverTargetsTheController(t *testing.T) {
	if err := Reclaim(os.Getpid(), 16<<20); err == nil {
		t.Fatal("controller reclaim accepted")
	}
}

func TestDeploymentConfiguresCompressionFromTheVerifiedRelease(t *testing.T) {
	out, err := exec.Command("bash", "../../scripts/dev/selftest/install-memory-compression.sh").CombinedOutput()
	if err != nil {
		t.Fatalf("deployment: %s %v", out, err)
	}
}
