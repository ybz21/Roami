package agentexecution

import (
	"context"
	"encoding/json"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/backend/project"
)

func TestNativeHoldRequiresExplicitStoppedConfirmation(t *testing.T) {
	for _, confirmed := range []bool{false, true} {
		t.Run(map[bool]string{false: "lost-owner", true: "confirmed-stop"}[confirmed], func(t *testing.T) {
			s := testService(t)
			directory := t.TempDir()
			input, send := io.Pipe()
			receive, output := io.Pipe()
			defer input.Close()
			defer receive.Close()
			spec := Spec{Key: "native-owner", Executor: "native", Directory: directory, TimeoutSeconds: 20}
			result := make(chan error, 1)
			go func() {
				result <- s.HoldNative(context.Background(), spec, json.NewDecoder(input), output)
				output.Close()
			}()
			decoder := json.NewDecoder(receive)
			var receipt Receipt
			if err := decoder.Decode(&receipt); err != nil {
				t.Fatal(err)
			}
			if receipt.Workspace == nil || receipt.Workspace.ID == "" {
				t.Fatalf("missing prepared receipt: %+v", receipt)
			}
			if _, err := s.claimWorkspace(context.Background(), directory, "overlap"); err == nil || err.Error() != "WORKSPACE_BUSY" {
				t.Fatalf("native/coding overlap: %v", err)
			}
			if confirmed {
				if err := json.NewEncoder(send).Encode(map[string]any{"state": "cancelled", "stopped": true}); err != nil {
					t.Fatal(err)
				}
				var ack map[string]bool
				if err := decoder.Decode(&ack); err != nil || !ack["released"] {
					t.Fatalf("release: %v %v", ack, err)
				}
			} else {
				send.Close()
			}
			err := <-result
			if confirmed && err != nil {
				t.Fatal(err)
			}
			if !confirmed && (err == nil || err.Error() != "NATIVE_WORKSPACE_OUTCOME_UNKNOWN") {
				t.Fatalf("lost holder reported stop: %v", err)
			}
			release, err := s.claimWorkspace(context.Background(), directory, "next-writer")
			if confirmed {
				if err != nil {
					t.Fatal(err)
				}
				release()
			} else if err == nil || err.Error() != "WORKSPACE_OUTCOME_UNKNOWN" {
				t.Fatalf("lost holder did not quarantine: %v", err)
			}
			send.Close()
		})
	}
}

func TestNativeProjectThroughRealPythonAndGoCLI(t *testing.T) {
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv required")
	}
	s := testService(t)
	db, err := s.platform(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	projectID, _ := project.NewStore(s.Runtime.DataDir, db).Add(directory, "Native project")
	repository, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	// Go's test cache must observe Python sources used by the child process.
	if err = filepath.WalkDir(filepath.Join(repository, "agent-runtime", "src"), func(path string, entry fs.DirEntry, problem error) error {
		if problem != nil {
			return problem
		}
		if !entry.IsDir() && strings.HasSuffix(path, ".py") {
			_, problem = os.ReadFile(path)
		}
		return problem
	}); err != nil {
		t.Fatal(err)
	}
	if _, err = os.ReadFile(filepath.Join(repository, "agent-runtime", "tests", "native_workspace_scenario.py")); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(t.TempDir(), "roami")
	build := exec.Command("go", "build", "-o", binary, "./cmd/roami")
	build.Dir = repository
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, output)
	}
	command := exec.Command("uv", "run", "--frozen", "--directory", filepath.Join(repository, "agent-runtime"), "python", "tests/native_workspace_scenario.py", binary, s.Runtime.HomeDir, projectID, directory)
	command.Env = append(os.Environ(), "ROAMI_HOME="+s.Runtime.HomeDir, "ROAMI_DATA="+s.Runtime.DataDir, "GIT_DIR=/foreign/repository", "GIT_INDEX_FILE=/foreign/index")
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("native project integration: %v\n%s", err, output)
	}
	if !strings.Contains(string(output), "native workspace scenario passed") {
		t.Fatalf("missing verification: %s", output)
	}
}
