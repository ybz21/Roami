package swarm

import (
	"bytes"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/agentruntime"
	metadb "github.com/ybz21/Roami/internal/storage"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestManagedCommandsRejectLegacyCompletion(t *testing.T) {
	for _, command := range []string{"done", "add", "adopt", "activate"} {
		err := Run(runtime.Runtime{}, []string{command, "sw-0123456789abcdef0123456789abcdef"}, io.Discard)
		if err == nil || !strings.Contains(err.Error(), "MANAGED_SWARM_USES_MAIN") {
			t.Fatalf("%s must use managed orchestration: err=%v", command, err)
		}
	}
}

func TestNewWithoutCommanderFlagUsesMainRuntime(t *testing.T) {
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	runtimePaths, err := agentruntime.Resolve(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Dir(runtimePaths.Socket), 0700); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("unix", runtimePaths.Socket)
	if err != nil {
		t.Fatal(err)
	}
	called := make(chan map[string]any, 1)
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/v1/swarms" || request.Method != "POST" || request.Header.Get("X-Roami-Owner") != "local" {
			t.Error("incorrect runtime boundary")
		}
		var body map[string]any
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		called <- body
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"data":{"id":"sw-0123456789abcdef0123456789abcdef"}}`)
	})}
	go server.Serve(listener)
	t.Cleanup(func() { _ = server.Close() })
	var output bytes.Buffer
	if err = Run(runtime.Runtime{HomeDir: root, DataDir: root}, []string{"new", "team", "--key", "request", "--goal", "build and verify"}, &output); err != nil {
		t.Fatal(err)
	}
	body := <-called
	if body["name"] != "team" || body["commandKey"] != "request" || body["mainConversationId"] != "" || !strings.Contains(output.String(), "sw-0123456789abcdef0123456789abcdef") {
		t.Fatalf("invalid default Main creation: %#v %s", body, &output)
	}
}

func TestManagedCreationRequiresIdempotencyKey(t *testing.T) {
	err := Run(runtime.Runtime{}, []string{"new", "team", "--main-conversation", "main", "--goal", "build"}, io.Discard)
	if err == nil || !strings.Contains(err.Error(), "requires --key") {
		t.Fatalf("creation must be safely retryable: err=%v", err)
	}
}
