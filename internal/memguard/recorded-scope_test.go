package memguard

import "testing"

func TestRecordedScopeRejectsPathsOutsideDedicatedCgroup(t *testing.T) {
	for _, path := range []string{"", "relative/tmux-spawn-one.scope", "/etc/tmux-spawn-one.scope", "/sys/fs/cgroup", "/sys/fs/cgroup/../tmux-spawn-one.scope", "/sys/fs/cgroup/user.slice/other.scope"} {
		if _, err := RecordedScopeProcesses(path); err == nil {
			t.Fatalf("accepted %q", path)
		}
	}
}
