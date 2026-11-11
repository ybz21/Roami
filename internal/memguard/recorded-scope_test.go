package memguard

import (
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestRecordedScopeRejectsPathsOutsideDedicatedCgroup(t *testing.T) {
	for _, path := range []string{"", "relative/tmux-spawn-one.scope", "/etc/tmux-spawn-one.scope", "/sys/fs/cgroup", "/sys/fs/cgroup/../tmux-spawn-one.scope", "/sys/fs/cgroup/user.slice/other.scope"} {
		if _, err := RecordedScopeProcesses(path); err == nil {
			t.Fatalf("accepted %q", path)
		}
	}
}

func TestRecordedScopeWaitsForRemovedCgroup(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "scope")
	if err := os.Mkdir(directory, 0700); err != nil {
		t.Fatal(err)
	}
	reads := 0
	processes, err := recordedScopeProcesses(directory, func(string) ([]int, error) {
		reads++
		if reads == 2 {
			if err := os.Remove(directory); err != nil {
				t.Fatal(err)
			}
		}
		return nil, &os.PathError{Op: "read", Path: filepath.Join(directory, "cgroup.procs"), Err: syscall.ENODEV}
	})
	if err != nil || len(processes) != 0 || reads != 2 {
		t.Fatalf("removed scope: %v %v (%d reads)", processes, err, reads)
	}
}

func TestRecordedScopeReadFailureDoesNotProveStopped(t *testing.T) {
	for _, failure := range []error{syscall.ENODEV, os.ErrPermission, os.ErrNotExist} {
		t.Run(failure.Error(), func(t *testing.T) {
			directory := t.TempDir()
			_, err := recordedScopeProcesses(directory, func(string) ([]int, error) {
				return nil, failure
			})
			if !errors.Is(err, failure) {
				t.Fatalf("lost observation error: %v", err)
			}
		})
	}
}

func TestRecordedScopeRetryRetainsLiveProcesses(t *testing.T) {
	reads := 0
	processes, err := recordedScopeProcesses(t.TempDir(), func(string) ([]int, error) {
		reads++
		if reads == 1 {
			return nil, syscall.ENODEV
		}
		return []int{123}, nil
	})
	if err != nil || len(processes) != 1 || processes[0] != 123 {
		t.Fatalf("live scope: %v %v", processes, err)
	}
}
