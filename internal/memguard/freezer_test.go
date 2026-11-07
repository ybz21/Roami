package memguard

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFreezerRefusesControllerAndMissingProcess(t *testing.T) {
	for _, pid := range []int{os.Getpid(), -1} {
		if _, err := FreezeState(pid); err == nil {
			t.Fatal("unsafe scope accepted")
		}
		if err := Freeze(pid, true); err == nil {
			t.Fatal("unsafe freeze accepted")
		}
	}
}

func TestPressureReadsSomeAverageWithoutUsingTotals(t *testing.T) {
	path := filepath.Join(t.TempDir(), "memory.pressure")
	if err := os.WriteFile(path, []byte("some avg10=12.50 avg60=1.0 avg300=0.1 total=999999\nfull avg10=3.0 avg60=0 avg300=0 total=99\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if got := pressureFile(path); got != 12.5 {
		t.Fatalf("pressure=%v", got)
	}
	if pressureFile(path+"-missing") != 0 {
		t.Fatal("missing PSI must not claim pressure")
	}
}

func TestWorkingSetIncludesSharedMemoryOnce(t *testing.T) {
	path := filepath.Join(t.TempDir(), "memory.stat")
	if err := os.WriteFile(path, []byte("anon 100\nfile 60\nshmem 40\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if got, ok := workingSet(path); !ok || got != 140 {
		t.Fatalf("working set=%d ok=%v", got, ok)
	}
}
