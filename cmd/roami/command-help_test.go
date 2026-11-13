package main

import (
	"bytes"
	"encoding/json"
	agentcommands "github.com/ybz21/Roami/agent-runtime"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestIndexedSubcommandHelpDoesNotInitializeResources(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, command := range []string{
		"session ls", "session capture", "session fork", "session rename", "session resolve", "session send",
		"chrome tabs", "chrome goto", "chrome screenshot", "chrome click", "chrome fill", "chrome eval", "chrome record", "chrome record start", "chrome record stop", "swarm status",
		"project ls", "project show", "agent capability list", "agent capability show",
	} {
		t.Run(command, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "uninitialized")
			args := append(strings.Fields(command), "--help")
			raw, _ := json.Marshal(args)
			cmd := exec.Command(executable, "-test.run=^TestSwarmCLIChild$")
			cmd.Env = append(os.Environ(), "ROAMI_SWARM_CLI_TEST_ARGS="+string(raw), "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_DATABASE_DIR="+filepath.Join(root, "database"), "ROAMI_BACKUP_DIR="+filepath.Join(root, "backups"), "ROAMI_CONFIG="+filepath.Join(root, "missing.yaml"), "ROAMI_SERVER=http://127.0.0.1:1", "TMUX_BIN="+filepath.Join(root, "unavailable-tmux"))
			output, err := cmd.CombinedOutput()
			if err != nil || len(output) == 0 {
				t.Fatalf("%v: %v %s", args, err, output)
			}
			if _, err = os.Stat(root); !os.IsNotExist(err) {
				t.Fatalf("help initialized resources: %v", args)
			}
		})
	}
}

func TestEveryCommandGuideHasLocalHelp(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	names := []string{"session", "session fork", "swarm"}
	for name := range commandGuides {
		names = append(names, name)
	}
	for name := range helpGroups {
		names = append(names, name)
	}
	for _, path := range agentcommands.Paths() {
		names = append(names, strings.Join(path, " "))
	}
	for _, name := range names {
		t.Run(name, func(t *testing.T) {
			var firstOutput []byte
			for _, form := range []string{"-h", "--help", "help", "topic-help"} {
				root := filepath.Join(t.TempDir(), "uninitialized")
				args := strings.Fields(name)
				if form == "help" {
					args = append([]string{"help"}, args...)
				} else {
					if form == "topic-help" {
						args = append(args, "help")
					} else {
						args = append(args, form)
					}
				}
				raw, _ := json.Marshal(args)
				cmd := exec.Command(executable, "-test.run=^TestSwarmCLIChild$")
				cmd.Env = append(os.Environ(), "ROAMI_SWARM_CLI_TEST_ARGS="+string(raw), "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_CONFIG="+filepath.Join(root, "missing.yaml"), "ROAMI_DATABASE_DIR="+filepath.Join(root, "database"), "ROAMI_BACKUP_DIR="+filepath.Join(root, "backups"), "ROAMI_SERVER=http://127.0.0.1:1", "TMUX_BIN="+filepath.Join(root, "unavailable-tmux"), "NO_COLOR=1")
				output, err := cmd.CombinedOutput()
				if err != nil {
					t.Fatalf("%v: %v\n%s", args, err, output)
				}
				if firstOutput == nil {
					firstOutput = output
				} else if !bytes.Equal(firstOutput, output) {
					t.Fatalf("help aliases differ: %v\n%s\n%s", args, firstOutput, output)
				}
				for _, want := range []string{"roami " + name, "\n用法\n", "进一步帮助："} {
					if !strings.Contains(string(output), want) {
						t.Fatalf("%v missing %q:\n%s", args, want, output)
					}
				}
				for command, want := range map[string]string{"session": "roami session <命令> [参数]", "session send": "roami session send SESSION TEXT", "swarm": "roami swarm <命令> [参数]", "swarm status": "roami swarm status SWARM_ID"} {
					if name == command && !strings.Contains(string(output), want) {
						t.Fatalf("native help replaced by registered transport: %v\n%s", args, output)
					}
				}
				if strings.Contains(string(output), "\x1b[") {
					t.Fatalf("help contains ANSI escapes: %q", output)
				}
				if _, err = os.Stat(root); !os.IsNotExist(err) {
					t.Fatalf("help initialized resources: %v (%v)", args, err)
				}
			}
		})
	}
}

func TestHelpAndArgumentErrorsUseSeparateStreams(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		args []string
		code int
		help bool
	}{
		{[]string{"project", "show", "-h"}, 0, true},
		{[]string{"project", "show", "--unknown-flag"}, 2, false},
	} {
		raw, _ := json.Marshal(tc.args)
		cmd := exec.Command(executable, "-test.run=^TestSwarmCLIChild$")
		cmd.Env = append(os.Environ(), "ROAMI_SWARM_CLI_TEST_ARGS="+string(raw))
		var stdout, stderr bytes.Buffer
		cmd.Stdout = &stdout
		cmd.Stderr = &stderr
		err = cmd.Run()
		code := 0
		if exit, ok := err.(*exec.ExitError); ok {
			code = exit.ExitCode()
		} else if err != nil {
			t.Fatal(err)
		}
		if code != tc.code {
			t.Fatalf("%v: %v %s", tc.args, err, stderr.String())
		}
		if tc.help && (!strings.Contains(stdout.String(), "用法") || stderr.Len() != 0) {
			t.Fatalf("help streams: stdout=%q stderr=%q", stdout.String(), stderr.String())
		}
		if !tc.help && (stdout.Len() != 0 || !strings.Contains(stderr.String(), "用法")) {
			t.Fatalf("error streams: stdout=%q stderr=%q", stdout.String(), stderr.String())
		}
	}
}
