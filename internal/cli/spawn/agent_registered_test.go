package spawn

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestRegisteredPromptFileLaunches(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("PATH", t.TempDir())
	for _, tc := range []struct{ kind, prefix string }{
		{"pi", "pi --print"},
		{"opencode", "opencode run"},
	} {
		t.Run(tc.kind, func(t *testing.T) {
			c := DefaultAgentConfig("/tmp")
			c.Kind = tc.kind
			got := c.CommandFromPromptFile("/tmp/agent prompt")
			if !strings.Contains(got, tc.prefix) || !strings.Contains(got, `"$(cat '/tmp/agent prompt')"`) {
				t.Fatalf("wrong launch: %s", got)
			}
		})
	}
}

func TestNativeOpenCodeLaunchOutsidePATH(t *testing.T) {
	home := filepath.Join(t.TempDir(), "user's home")
	t.Setenv("HOME", home)
	t.Setenv("PATH", t.TempDir())
	path := filepath.Join(home, ".opencode", "bin", "opencode")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\"\n"), 0700); err != nil {
		t.Fatal(err)
	}
	for _, interactive := range []bool{false, true} {
		c := AgentConfig{Kind: "opencode", Workdir: home, Interactive: interactive}
		command := c.Command("test prompt")
		out, err := exec.Command("/bin/sh", "-c", command).CombinedOutput()
		want := "run\ntest prompt\n"
		if interactive {
			want = "--prompt\ntest prompt\n"
		}
		if err != nil || string(out) != want {
			t.Fatalf("interactive=%v: %s: %s, %v", interactive, command, out, err)
		}
	}
}
