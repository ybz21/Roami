package agentexecution

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
)

func writeProcFixture(t *testing.T, root string, pid int) {
	t.Helper()
	directory := filepath.Join(root, strconv.Itoa(pid))
	if err := os.MkdirAll(directory, 0700); err != nil {
		t.Fatal(err)
	}
	fields := []string{"S", "1"}
	for len(fields) < 19 {
		fields = append(fields, "0")
	}
	fields = append(fields, "12345")
	if err := os.WriteFile(filepath.Join(directory, "stat"), []byte(fmt.Sprintf("%d (fixture) %s", pid, strings.Join(fields, " "))), 0600); err != nil {
		t.Fatal(err)
	}
}

func TestProcStatDescriptorAfterOwnedProcessExit(t *testing.T) {
	if _, err := os.Stat("/proc/self/stat"); err != nil {
		t.Skip("requires Linux procfs")
	}
	command := exec.Command("cat")
	input, err := command.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err = command.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_ = input.Close()
		if command.ProcessState == nil {
			_ = command.Process.Kill()
			_ = command.Wait()
		}
	})
	pid := command.Process.Pid
	stat, err := os.Open(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
	if err != nil {
		t.Fatal(err)
	}
	defer stat.Close()
	root := t.TempDir()
	writeProcFixture(t, root, os.Getpid())
	writeProcFixture(t, root, pid)
	var observed error
	snapshot, err := processSnapshotFromProc(root, func(path string) ([]byte, error) {
		if filepath.Base(filepath.Dir(path)) != strconv.Itoa(pid) {
			return os.ReadFile(path)
		}
		if err := input.Close(); err != nil {
			t.Fatal(err)
		}
		if err := command.Wait(); err != nil {
			t.Fatal(err)
		}
		if err := os.RemoveAll(filepath.Dir(path)); err != nil {
			t.Fatal(err)
		}
		data, err := io.ReadAll(stat)
		observed = err
		return data, err
	})
	if !errors.Is(observed, syscall.ESRCH) {
		t.Fatalf("expected a real exited-task ESRCH, got %v", observed)
	}
	if err != nil || snapshot[os.Getpid()].Token != "12345" || snapshot[pid].Token != "" {
		t.Fatalf("exited task invalidated the surviving process: %v %v", snapshot, err)
	}
	if sessionProcessesStopped(SessionBinding{PID: pid, Scope: "missing", Processes: map[int]string{pid: "12345"}}) {
		t.Fatal("loss of the target root must not prove stopped")
	}
}

func TestProcessObservationKeepsAmbiguousErrorsClosed(t *testing.T) {
	for _, problem := range []error{syscall.ESRCH, syscall.EACCES, syscall.EIO} {
		for _, removed := range []bool{false, true} {
			t.Run(fmt.Sprintf("%v/removed=%v", problem, removed), func(t *testing.T) {
				root := t.TempDir()
				writeProcFixture(t, root, 100)
				_, err := processSnapshotFromProc(root, func(path string) ([]byte, error) {
					if removed {
						if err := os.RemoveAll(filepath.Dir(path)); err != nil {
							t.Fatal(err)
						}
					}
					return nil, &os.PathError{Op: "read", Path: path, Err: problem}
				})
				if errors.Is(problem, syscall.ESRCH) && removed {
					if err != nil {
						t.Fatal(err)
					}
				} else if err == nil || err.Error() != "SESSION_PROCESS_OBSERVATION_UNAVAILABLE" {
					t.Fatalf("uncertain process observation was accepted: %v", err)
				}
			})
		}
	}
}
