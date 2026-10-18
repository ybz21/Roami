package runtime

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func pasteRuntime(t *testing.T, failPaste bool) (Runtime, string) {
	t.Helper()
	directory := t.TempDir()
	binary := filepath.Join(directory, "tmux")
	failure := "False"
	if failPaste {
		failure = "True"
	}
	script := `#!/usr/bin/env python3
import json, pathlib, sys
root=pathlib.Path(__file__).parent
with (root/'calls').open('a') as output: output.write(json.dumps(sys.argv[1:])+'\n')
if sys.argv[1]=='load-buffer': (root/'buffer').write_bytes(sys.stdin.buffer.read())
if sys.argv[1]=='paste-buffer' and ` + failure + `: sys.exit(3)
`
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	return Runtime{TmuxBin: binary}, directory
}

func pasteCalls(t *testing.T, directory string) [][]string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(directory, "calls"))
	if err != nil {
		t.Fatal(err)
	}
	var calls [][]string
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		var call []string
		if json.Unmarshal([]byte(line), &call) != nil {
			t.Fatal("invalid fixture call")
		}
		calls = append(calls, call)
	}
	return calls
}

func TestShellSubmitUsesStdinAndExactlyOneEnter(t *testing.T) {
	rt, directory := pasteRuntime(t, false)
	command := "fixture " + strings.Repeat("长提示词", 100_000)
	if err := rt.SendShellCommand("=own-session", command); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(filepath.Join(directory, "buffer"))
	if string(data) != command {
		t.Fatal("large input truncated")
	}
	enters := 0
	for _, call := range pasteCalls(t, directory) {
		if len(strings.Join(call, " ")) > 512 {
			t.Fatal("input leaked into command argv")
		}
		if call[0] == "send-keys" {
			enters++
			if strings.Join(call, " ") != "send-keys -t =own-session Enter" {
				t.Fatal("unsafe submit target")
			}
		}
	}
	if enters != 1 {
		t.Fatal("shell launch may confirm a subsequent TUI prompt")
	}
}

func TestPasteForRestoreNeverSubmitsAndFailureNeverPressesEnter(t *testing.T) {
	for _, failPaste := range []bool{false, true} {
		rt, directory := pasteRuntime(t, failPaste)
		var err error
		if failPaste {
			err = rt.SendShellCommand("=own-session", "command")
		} else {
			err = rt.PasteInput("=own-session", "resume command")
		}
		if (err != nil) != failPaste {
			t.Fatalf("paste failure: %v", err)
		}
		cleaned := false
		for _, call := range pasteCalls(t, directory) {
			if call[0] == "send-keys" {
				t.Fatal("restore or failed paste submitted")
			}
			cleaned = cleaned || call[0] == "delete-buffer"
		}
		if !cleaned {
			t.Fatal("private paste buffer leaked")
		}
	}
}
