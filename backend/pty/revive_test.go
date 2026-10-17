package pty

import (
	"strings"
	"testing"
	"time"
)

func TestReviveAdapterUsesCoreWithoutInstalledCLI(t *testing.T) {
	root := t.TempDir()
	for _, prefix := range []string{"ROAMI", "ROAM", "TTMUX"} {
		for _, suffix := range []string{"HOME", "DATA", "CONFIG", "DATABASE_DIR", "BACKUP_DIR", "BIN"} {
			t.Setenv(prefix+"_"+suffix, "")
		}
	}
	t.Setenv("ROAMI_HOME", root)
	t.Setenv("ROAMI_DATA", root)
	t.Setenv("PATH", t.TempDir())
	out, err := ttmuxRun(time.Second, "help")
	if err != nil || !strings.Contains(out, "roami session") {
		t.Fatalf("in-process core unavailable: output=%q error=%v", out, err)
	}
}
