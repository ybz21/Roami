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

func TestAgentIdentityChild(t *testing.T) {
	if os.Getenv("ROAMI_IDENTITY_FIXTURE") != "1" {
		t.Skip("subprocess fixture")
	}
	if os.Getenv("ROAMI_WAKE_FIXTURE") == "1" {
		os.Exit(runAgent([]string{"wake", "--conversation", "original-main", "--project", "project", "--key", "daily", "--file", "-"}))
	}
	os.Exit(runAgent([]string{"identity", "--conversation", "original-main"}))
}

func TestAgentIdentityReadsWithoutCreatingOrSending(t *testing.T) {
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
	if err = os.MkdirAll(filepath.Dir(paths.Socket), 0700); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("unix", paths.Socket)
	if err != nil {
		t.Fatal(err)
	}
	requests := make(chan string, 4)
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests <- r.Method + " " + r.URL.Path
		if r.Method != "GET" || r.URL.Path != "/v1/conversations/original-main/identity" {
			w.WriteHeader(405)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"kind":"project_main","projectId":"project","conversationId":"original-main","activeBranchId":"branch"}}`))
	})}
	defer server.Close()
	go server.Serve(listener)
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	command := exec.Command(executable, "-test.run=^TestAgentIdentityChild$")
	command.Env = append(os.Environ(), "ROAMI_IDENTITY_FIXTURE=1", "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_DATABASE_DIR="+paths.Storage.Database)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("%v: %s", err, output)
	}
	var response struct {
		Data struct{ Kind, ProjectID, ConversationID string }
	}
	if err = json.Unmarshal(output, &response); err != nil || response.Data.Kind != "project_main" || response.Data.ProjectID != "project" || response.Data.ConversationID != "original-main" {
		t.Fatalf("%s %v", output, err)
	}
	if got := <-requests; got != "GET /v1/conversations/original-main/identity" {
		t.Fatal(got)
	}
	if len(requests) != 0 {
		t.Fatal("identity performed additional requests")
	}
}

func TestAgentWakeUsesScopedEndpointAndLiteralInput(t *testing.T) {
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
	if err = os.MkdirAll(filepath.Dir(paths.Socket), 0700); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("unix", paths.Socket)
	if err != nil {
		t.Fatal(err)
	}
	requests := make(chan map[string]string, 2)
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/v1/conversations/original-main/wake" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
			w.WriteHeader(405)
			return
		}
		var payload map[string]string
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Error(err)
		}
		requests <- payload
		w.WriteHeader(202)
		_, _ = w.Write([]byte(`{"data":{"kind":"message","messageId":"message","turnId":"turn"}}`))
	})}
	defer server.Close()
	go server.Serve(listener)
	executable, _ := os.Executable()
	command := exec.Command(executable, "-test.run=^TestAgentIdentityChild$")
	command.Env = append(os.Environ(), "ROAMI_IDENTITY_FIXTURE=1", "ROAMI_WAKE_FIXTURE=1", "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_DATABASE_DIR="+paths.Storage.Database, "ROAMI_AGENT_CALLER_ROLE=", "ROAMI_AGENT_TURN_ID=")
	command.Stdin = strings.NewReader("Keep the original Main. $(echo literal)\nSecond line")
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("%v: %s", err, output)
	}
	payload := <-requests
	if payload["projectId"] != "project" || payload["requestKey"] != "daily" || payload["text"] != "Keep the original Main. $(echo literal)\nSecond line" {
		t.Fatal(payload)
	}
	command = exec.Command(executable, "-test.run=^TestAgentIdentityChild$")
	command.Env = append(os.Environ(), "ROAMI_IDENTITY_FIXTURE=1", "ROAMI_WAKE_FIXTURE=1", "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_DATABASE_DIR="+paths.Storage.Database, "ROAMI_AGENT_CALLER_ROLE=main")
	output, err = command.CombinedOutput()
	if err == nil || !strings.Contains(string(output), "EXTERNAL_TRIGGER_REQUIRED") || len(requests) != 0 {
		t.Fatalf("native caller reached wake endpoint: %s %v", output, err)
	}
}
