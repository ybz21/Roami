package app

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestUnsupportedCommandsNeverReachTmux(t *testing.T) {
	for _, args := range [][]string{{"kill-server"}, {"killall"}, {"source"}, {"list-sessions", ";", "kill-server"}, {"-S", "/production", "kill-server"}, {"run-shell", "false"}, {"typo"}} {
		t.Run(args[0], func(t *testing.T) {
			root := t.TempDir()
			marker := filepath.Join(root, "invoked")
			binary := filepath.Join(root, "tmux")
			if err := os.WriteFile(binary, []byte("#!/bin/sh\ntouch '"+marker+"'\n"), 0700); err != nil {
				t.Fatal(err)
			}
			a := App{rt: runtime.Runtime{TmuxBin: binary, HomeDir: root, DataDir: root}, out: io.Discard}
			if err := a.Run(args); err == nil {
				t.Fatal("unsupported command accepted")
			}
			if _, err := os.Stat(marker); !os.IsNotExist(err) {
				t.Fatal("unsupported command reached tmux")
			}
		})
	}
}
