package agentexecution

import (
	"bufio"
	"encoding/json"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"syscall"
	"testing"
	"time"
)

func TestCodeModeProcessFixture(t *testing.T) {
	if os.Getenv("ROAMI_CODE_MODE_FIXTURE") != "1" {
		return
	}
	var args []string
	for i, arg := range os.Args {
		if arg == "--" {
			args = os.Args[i+1:]
			break
		}
	}
	if len(args) < 3 {
		os.Exit(2)
	}
	if args[0] == "provider" {
		if err := os.WriteFile(args[2]+".ready", []byte("ready"), 0600); err != nil {
			os.Exit(3)
		}
		input := bufio.NewScanner(os.Stdin)
		if !input.Scan() {
			return
		}
		child := exec.Command(args[1], "-test.run=TestCodeModeProcessFixture", "--", "host", args[2], args[3])
		child.Env = os.Environ()
		if child.Start() != nil {
			os.Exit(4)
		}
		defer func() { _ = child.Process.Signal(syscall.SIGTERM); _ = child.Wait() }()
		for input.Scan() {
		}
	} else if args[0] == "host" {
		stopped := make(chan os.Signal, 1)
		signal.Notify(stopped, syscall.SIGTERM)
		defer signal.Stop(stopped)
		state := map[string]int{"host": os.Getpid()}
		if args[2] == "worker" {
			child := exec.Command("/bin/sleep", "60")
			if child.Start() != nil {
				os.Exit(5)
			}
			state["worker"] = child.Process.Pid
			defer func() { _ = child.Process.Kill(); _ = child.Wait() }()
		}
		raw, _ := json.Marshal(state)
		if os.WriteFile(args[1], raw, 0600) != nil {
			os.Exit(6)
		}
		<-stopped
	}
}

func copyCodeModeExecutable(t *testing.T, path string) {
	t.Helper()
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(binary)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, raw, 0700); err != nil {
		t.Fatal(err)
	}
}

func waitCodeModeFile(t *testing.T, path string) []byte {
	t.Helper()
	until := time.Now().Add(5 * time.Second)
	for time.Now().Before(until) {
		if raw, err := os.ReadFile(path); err == nil && len(raw) > 0 {
			return raw
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("fixture did not start")
	return nil
}

func TestCodeModeHostPreservesTaskProcessBoundaries(t *testing.T) {
	for _, mode := range []string{"bundled", "other-directory", "wrong-provider", "worker"} {
		t.Run(mode, func(t *testing.T) {
			s, binding := sessionFixture(t)
			_ = s
			root := t.TempDir()
			provider := filepath.Join(root, "codex")
			host := filepath.Join(root, "codex-code-mode-host")
			if mode == "other-directory" {
				host = filepath.Join(root, "other", "codex-code-mode-host")
			}
			if mode == "wrong-provider" {
				provider = filepath.Join(root, "other-agent")
			}
			copyCodeModeExecutable(t, provider)
			copyCodeModeExecutable(t, host)
			if mode == "other-directory" {
				copyCodeModeExecutable(t, filepath.Join(root, "codex-code-mode-host"))
			}
			stateFile := filepath.Join(root, "process.json")
			worker := "none"
			if mode == "worker" {
				worker = "worker"
			}
			command := exec.Command(provider, "-test.run=TestCodeModeProcessFixture", "--", "provider", host, stateFile, worker)
			command.Env = append(os.Environ(), "ROAMI_CODE_MODE_FIXTURE=1")
			input, err := command.StdinPipe()
			if err != nil {
				t.Fatal(err)
			}
			if err = command.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() {
				_ = input.Close()
				done := make(chan error, 1)
				go func() { done <- command.Wait() }()
				select {
				case <-done:
				case <-time.After(5 * time.Second):
					_ = command.Process.Kill()
					<-done
				}
			})
			waitCodeModeFile(t, stateFile+".ready")
			initial, scope, baseline, err := paneProcessSnapshot(binding.PID)
			if err != nil {
				t.Fatal(err)
			}
			binding.Scope, binding.Processes = scope, baseline
			binding.ForeignProcesses = map[int]string{}
			owned := descendantProcesses(initial, binding.PID)
			for pid, token := range baseline {
				if owned[pid] == "" {
					binding.ForeignProcesses[pid] = token
				}
			}
			if _, err = input.Write([]byte("start\n")); err != nil {
				t.Fatal(err)
			}
			var pids map[string]int
			if err = json.Unmarshal(waitCodeModeFile(t, stateFile), &pids); err != nil {
				t.Fatal(err)
			}
			snapshot, err := processSnapshot()
			if err != nil {
				t.Fatal(err)
			}
			expected := mode == "bundled" || mode == "worker"
			if got := codexCodeModeHost(binding, snapshot, pids["host"]); got != expected {
				t.Fatalf("host %s classification=%v", mode, got)
			}
			if got := sessionProcessesStopped(binding); got != (mode == "bundled") {
				t.Fatalf("process proof %s=%v", mode, got)
			}
			if mode == "bundled" {
				for _, pid := range []int{pids["host"], command.Process.Pid} {
					changed := snapshot[pid]
					changed.Token = "recycled-" + strconv.Itoa(pid)
					snapshot[pid] = changed
					if codexCodeModeHost(binding, snapshot, pids["host"]) {
						t.Fatal("changed process identity accepted")
					}
					snapshot, err = processSnapshot()
					if err != nil {
						t.Fatal(err)
					}
				}
			}
		})
	}
}
