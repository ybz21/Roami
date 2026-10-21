package main

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"testing"
)

func TestADBChildProcess(t *testing.T) {
	encoded := os.Getenv("ROAMI_ADB_TEST_ARGS")
	if encoded == "" {
		t.Skip("subprocess fixture")
	}
	var args []string
	if err := json.Unmarshal([]byte(encoded), &args); err != nil {
		t.Fatal(err)
	}
	handled, code := runCLI(args, "")
	if !handled {
		t.Fatal("ADB command was not handled")
	}
	os.Exit(code)
}

func adbProcess(t *testing.T, args []string) *exec.Cmd {
	t.Helper()
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := json.Marshal(args)
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(binary, "-test.run=^TestADBChildProcess$")
	cmd.Env = append(os.Environ(), "ROAMI_ADB_TEST_ARGS="+string(encoded))
	return cmd
}

func TestADBPreservesArgumentsStreamsAndExitStatus(t *testing.T) {
	dir := t.TempDir()
	arguments := filepath.Join(dir, "arguments.json")
	script := `#!/usr/bin/env python3
import json, os, sys
with open(os.environ['ROAMI_ADB_TEST_CAPTURE'], 'w') as f:
    json.dump(sys.argv[1:], f)
sys.stdout.buffer.write(sys.stdin.buffer.read())
sys.stderr.write('fixture stderr\n')
sys.exit(23)
`
	if err := os.WriteFile(filepath.Join(dir, "adb"), []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name string
		args []string
		want []string
	}{
		{"device and literal shell arguments", []string{"adb", "-s", "device with spaces", "shell", "printf", "$(must-not-run); 'quoted'"}, []string{"-s", "device with spaces", "shell", "printf", "$(must-not-run); 'quoted'"}},
		{"binary capture", []string{"adb", "-s", "fixture", "exec-out", "screencap", "-p"}, []string{"-s", "fixture", "exec-out", "screencap", "-p"}},
		{"default help", []string{"adb"}, []string{"help"}},
		{"top-level help", []string{"help", "adb"}, []string{"help"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			cmd := adbProcess(t, tc.args)
			cmd.Env = append(cmd.Env, "PATH="+dir+string(os.PathListSeparator)+os.Getenv("PATH"), "ROAMI_ADB_TEST_CAPTURE="+arguments)
			payload := []byte{'\x89', 'P', 'N', 'G', '\r', '\n', '\x1a', '\n', 0, 255}
			cmd.Stdin = bytes.NewReader(payload)
			var stdout, stderr bytes.Buffer
			cmd.Stdout, cmd.Stderr = &stdout, &stderr
			err := cmd.Run()
			if exit, ok := err.(*exec.ExitError); !ok || exit.ExitCode() != 23 {
				t.Fatalf("lost ADB exit status: %v, %s", err, stderr.String())
			}
			if !bytes.Equal(stdout.Bytes(), payload) || stderr.String() != "fixture stderr\n" {
				t.Fatalf("changed ADB streams: stdout=%q stderr=%q", stdout.Bytes(), stderr.String())
			}
			data, err := os.ReadFile(arguments)
			if err != nil {
				t.Fatal(err)
			}
			var got []string
			if err := json.Unmarshal(data, &got); err != nil || !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("changed ADB arguments: got=%q want=%q err=%v", got, tc.want, err)
			}
		})
	}
}

func TestADBMissingBinaryReturnsFailure(t *testing.T) {
	cmd := adbProcess(t, []string{"adb", "devices", "-l"})
	cmd.Env = append(cmd.Env, "PATH="+t.TempDir())
	output, err := cmd.CombinedOutput()
	if exit, ok := err.(*exec.ExitError); !ok || exit.ExitCode() != 1 || !bytes.Contains(output, []byte("adb")) {
		t.Fatalf("missing ADB not reported: %v %s", err, output)
	}
}
