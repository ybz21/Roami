package main

import (
	"encoding/json"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/agentruntime"
	core "github.com/ybz21/Roami/internal/storage"
)

func TestAgentLegacyUserCommandChild(t *testing.T) {
	if os.Getenv("ROAMI_LEGACY_COMMAND_FIXTURE") != "1" {
		t.Skip("subprocess fixture")
	}
	var args []string
	if err := json.Unmarshal([]byte(os.Getenv("ROAMI_LEGACY_COMMAND_ARGS")), &args); err != nil {
		t.Fatal(err)
	}
	os.Exit(runAgent(args))
}

func TestAgentLegacyWritesKeepUserAndToolContextsSeparate(t *testing.T) {
	root := t.TempDir()
	db, err := core.Open(root, core.Options{HomeDir: root, DataDir: root})
	if err != nil {
		t.Fatal(err)
	}
	db.Close()
	paths, err := agentruntime.Resolve(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(paths.Socket), 0700); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("unix", paths.Socket)
	if err != nil {
		t.Fatal(err)
	}
	type request struct {
		method, path string
		body         map[string]any
	}
	requests := make(chan request, 32)
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		requests <- request{r.Method, r.URL.Path, body}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"state":"accepted","operationId":"original-operation"}}`))
	})}
	defer server.Close()
	go server.Serve(listener)
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	text := "Keep this literal: $(echo literal)\nContinue the original instance."
	commands := []struct {
		name, path, field string
		args              []string
	}{
		{"new", "/v1/conversations", "title", []string{"new", "--title", text, "--key", "original-key"}},
		{"send", "/v1/conversations/original-main/messages", "text", []string{"send", "--conversation", "original-main", "--key", "original-key", "--text", text}},
		{"notify", "/internal/notify", "text", []string{"notify", "--conversation", "original-main", "--source", "fixture", "--key", "original-key", "--text", text}},
		{"steer", "/v1/tasks/original-task/steer", "text", []string{"steer", "--task", "original-task", "--revision", "7", "--key", "original-key", "--text", text}},
	}
	callers := []struct {
		name string
		env  []string
	}{
		{"external", nil},
		{"main", []string{"ROAMI_AGENT_CALLER_ROLE=main"}},
		{"worker", []string{"ROAMI_AGENT_CALLER_ROLE=worker"}},
		{"research", []string{"ROAMI_AGENT_CALLER_ROLE=research"}},
		{"turn_only", []string{"ROAMI_AGENT_TURN_ID=original-turn"}},
		{"call_only", []string{"ROAMI_AGENT_TOOL_CALL_ID=original-call"}},
		{"complete_context", []string{"ROAMI_AGENT_CALLER_ROLE=worker", "ROAMI_AGENT_TURN_ID=original-turn", "ROAMI_AGENT_TOOL_CALL_ID=original-call"}},
	}
	for _, command := range commands {
		for _, caller := range callers {
			t.Run(command.name+"/"+caller.name, func(t *testing.T) {
				args, _ := json.Marshal(command.args)
				child := exec.Command(executable, "-test.run=^TestAgentLegacyUserCommandChild$")
				child.Env = append(os.Environ(), "ROAMI_LEGACY_COMMAND_FIXTURE=1", "ROAMI_LEGACY_COMMAND_ARGS="+string(args), "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_DATABASE_DIR="+paths.Storage.Database, "ROAMI_AGENT_CALLER_ROLE=", "ROAMI_AGENT_TURN_ID=", "ROAMI_AGENT_TOOL_CALL_ID=")
				child.Env = append(child.Env, caller.env...)
				output, err := child.CombinedOutput()
				if caller.name != "external" {
					if err == nil || !strings.Contains(string(output), "USE_REGISTERED_CLI_CAPABILITY") {
						t.Errorf("managed caller reached user command: %v %s", err, output)
					}
					select {
					case got := <-requests:
						t.Errorf("managed caller wrote %s %s", got.method, got.path)
					default:
					}
					return
				}
				if err != nil {
					t.Fatalf("external caller rejected: %v %s", err, output)
				}
				var got request
				select {
				case got = <-requests:
				default:
					t.Fatal("user command returned without its request")
				}
				if got.method != "POST" || got.path != command.path || got.body[command.field] != text {
					t.Fatalf("user command changed target or input: %#v", got)
				}
				if command.name == "steer" && got.body["revision"] != float64(7) {
					t.Fatalf("revision lost: %#v", got.body)
				}
				if len(requests) != 0 {
					t.Fatal("additional requests")
				}
			})
		}
	}
}
