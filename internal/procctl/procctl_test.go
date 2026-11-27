package procctl

import (
	"os"
	"os/exec"
	"runtime"
	"testing"
	"time"
)

func TestProcessAliveAndKillGroup(t *testing.T) {
	if !ProcessAlive(os.Getpid()) {
		t.Fatalf("current process should be alive")
	}
	if ProcessAlive(0) || ProcessAlive(-1) {
		t.Fatalf("non-positive PID must not report alive")
	}

	if runtime.GOOS == "windows" {
		return
	}
	cmd := exec.Command("sh", "-c", "sleep 30")
	SetProcessGroup(cmd)
	if err := cmd.Start(); err != nil {
		t.Fatalf("start child: %v", err)
	}
	if !ProcessAlive(cmd.Process.Pid) {
		t.Fatalf("started child should be alive")
	}
	TerminateGroup(cmd.Process, 50*time.Millisecond)
	_ = cmd.Wait()
	if ProcessAlive(cmd.Process.Pid) {
		t.Fatalf("terminated child should not be alive")
	}
}
