package memguard

import (
	"os"
	"os/exec"
	"strconv"
	"strings"
	"testing"
)

func TestProcessStatHandlesParenthesesInNames(t *testing.T) {
	fields := []string{"S", "42"}
	for len(fields) < 19 {
		fields = append(fields, "0")
	}
	fields = append(fields, "123456")
	parent, state, start, err := processStat("100 (worker (build)) " + strings.Join(fields, " "))
	if err != nil || parent != 42 || state != "S" || start != "123456" {
		t.Fatalf("%d %s %s %v", parent, state, start, err)
	}
	for _, bad := range []string{"", "100 (broken", "100 (name) S 42"} {
		if _, _, _, err := processStat(bad); err == nil {
			t.Fatalf("accepted %q", bad)
		}
	}
}

func TestProcessSignalChecksIdentityAndScope(t *testing.T) {
	cmd := exec.Command("sleep", "60")
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = cmd.Process.Kill(); _ = cmd.Wait() }()
	p, err := readProcess(cmd.Process.Pid)
	if err != nil {
		t.Fatal(err)
	}
	scope := cgroupDir(p.PID)
	if scope == "" {
		t.Skip("requires Linux cgroups")
	}
	for _, tc := range []struct {
		start  string
		scopes map[string]bool
	}{
		{"", map[string]bool{scope: true}},
		{p.Start + "1", map[string]bool{scope: true}},
		{p.Start, map[string]bool{scope + "-other": true}},
		{p.Start, map[string]bool{}},
	} {
		if err := signalProcess(p.PID, tc.start, true, tc.scopes); err == nil {
			t.Fatal("unsafe process signal accepted")
		}
		if _, err := os.Stat("/proc/" + strconv.Itoa(p.PID)); err != nil {
			t.Fatal("child disappeared after rejected signal")
		}
	}
	if err := signalProcess(p.PID, p.Start, false, map[string]bool{scope: true}); err != nil {
		t.Fatal(err)
	}
	if err := cmd.Wait(); err == nil {
		t.Fatal("child should exit on SIGTERM")
	}
}

func TestProcessesRefusesControllerAndNonexistentPane(t *testing.T) {
	for _, panes := range [][]int{nil, {os.Getpid()}, {2147483647}} {
		if _, err := Processes(panes); err == nil {
			t.Fatal("accepted unsafe pane scope")
		}
	}
}
