package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/agentruntime"
	metadb "github.com/ybz21/Roami/internal/storage"
	"golang.org/x/sys/unix"
)

func TestAgentServeParentHelper(t *testing.T) {
	if os.Getenv("ROAMI_PARENT_FIXTURE") != "1" {
		return
	}
	storage, err := metadb.ResolvePaths(os.Getenv("ROAMI_HOME"), os.Getenv("ROAMI_DATA"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = storage.Ensure(); err != nil {
		t.Fatal(err)
	}
	paths, err := agentruntime.Resolve(os.Getenv("ROAMI_HOME"), os.Getenv("ROAMI_DATA"))
	if err != nil {
		t.Fatal(err)
	}
	if err = agentPython(os.Getenv("ROAMI_PARENT_RUNTIME"), paths, false); err != nil {
		t.Fatal(err)
	}
}

func TestAgentServeFollowsParentLifetime(t *testing.T) {
	source, err := os.ReadFile("../../cases/case-79-mech-ap01/input/scenarios.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Signals []string `json:"signals"`
	}
	if err = json.Unmarshal(source, &fixture); err != nil {
		t.Fatal(err)
	}
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Fatal("Python required for real parent-lifetime regression")
	}
	for _, name := range fixture.Signals {
		t.Run(name, func(t *testing.T) {
			root, err := os.MkdirTemp("", "roami-ap-")
			if err != nil {
				t.Fatal(err)
			}
			defer os.RemoveAll(root)
			childFile := filepath.Join(root, "child.pid")
			childExit := filepath.Join(root, "child.exited")
			executable := filepath.Join(root, "python-fixture")
			program := fmt.Sprintf("#!%s\nimport os,sys,pathlib,time\npathlib.Path(%q).write_text(str(os.getpid()))\nif '--parent-fd' in sys.argv:\n fd=int(sys.argv[sys.argv.index('--parent-fd')+1])\n while os.read(fd,1): pass\n pathlib.Path(%q).write_text('parent closed')\nelse:\n while True: time.sleep(1)\n", python, childFile, childExit)
			if err = os.WriteFile(executable, []byte(program), 0700); err != nil {
				t.Fatal(err)
			}
			parent := exec.Command(os.Args[0], "-test.run=^TestAgentServeParentHelper$")
			parent.Env = append(agentEnvironment(), "ROAMI_PARENT_FIXTURE=1", "ROAMI_PARENT_RUNTIME="+root, "ROAMI_AGENT_PYTHON="+executable, "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_CONFIG="+filepath.Join(root, "config.yaml"), "ROAMI_DATABASE_DIR="+filepath.Join(root, "database"))
			output, err := os.Create(filepath.Join(root, "parent.log"))
			if err != nil {
				t.Fatal(err)
			}
			defer output.Close()
			parent.Stdout = output
			parent.Stderr = output
			if err = parent.Start(); err != nil {
				t.Fatal(err)
			}
			waited := false
			childFD := -1
			defer func() {
				if !waited {
					_ = parent.Process.Kill()
					_ = parent.Wait()
				}
				if childFD >= 0 {
					_ = unix.PidfdSendSignal(childFD, syscall.SIGKILL, nil, 0)
					_ = unix.Close(childFD)
				}
			}()
			deadline := time.Now().Add(5 * time.Second)
			var pid int
			for time.Now().Before(deadline) {
				if body, e := os.ReadFile(childFile); e == nil {
					pid, _ = strconv.Atoi(string(body))
					break
				}
				time.Sleep(10 * time.Millisecond)
			}
			if pid <= 0 {
				body, _ := os.ReadFile(filepath.Join(root, "parent.log"))
				t.Fatalf("child not started: %s", body)
			}
			childFD, err = unix.PidfdOpen(pid, 0)
			if err != nil {
				t.Fatal(err)
			}
			sig := syscall.SIGTERM
			if name == "kill" {
				sig = syscall.SIGKILL
			}
			if err = parent.Process.Signal(sig); err != nil {
				t.Fatal(err)
			}
			_ = parent.Wait()
			waited = true
			events := []unix.PollFd{{Fd: int32(childFD), Events: unix.POLLIN}}
			if _, err = unix.Poll(events, 5000); err != nil || events[0].Revents&unix.POLLIN == 0 {
				t.Fatalf("owned Python runtime survived parent %s: %v", name, err)
			}
			if body, e := os.ReadFile(childExit); e != nil || string(body) != "parent closed" {
				t.Fatalf("child did not observe parent pipe EOF: %q %v", body, e)
			}
		})
	}
}
