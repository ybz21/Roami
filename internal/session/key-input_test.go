package session

import (
	"github.com/ybz21/Roami/internal/tmuxruntime"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestKeyInputBindsOneSessionAndRejectsTmuxOptions(t *testing.T) {
	root := t.TempDir()
	calls := filepath.Join(root, "keys")
	binary := filepath.Join(root, "tmux")
	script := "#!/bin/sh\ncase \"$1\" in\nlist-sessions) printf '$1\\t1792200000\\t2026-1017-0900-0001\\tlabel\\n';;\nsend-keys) printf '%s\\n' \"$@\" > '" + calls + "';;\nesac\n"
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	rt := runtime.Runtime{TmuxBin: binary}
	if err := Keys(rt, []string{"2026-1017-0900-0001", "Down", "Enter"}, io.Discard); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(calls)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "send-keys\n-t\n=2026-1017-0900-0001:\nDown\nEnter\n" {
		t.Fatalf("unexpected key target: %s", data)
	}
	if err := os.Remove(calls); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"-t", ";", "kill-server", "C-m", "two words"} {
		if err := Keys(rt, []string{"2026-1017-0900-0001", key}, io.Discard); err == nil {
			t.Fatalf("accepted %q", key)
		}
	}
	if _, err := os.Stat(calls); !os.IsNotExist(err) {
		t.Fatal("rejected key reached tmux")
	}
}
