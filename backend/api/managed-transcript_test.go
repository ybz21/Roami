package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/agentlifecycle"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestProviderTranscriptIgnoresNewerSameDirectoryConversation(t *testing.T) {
	root := t.TempDir()
	a := "11111111-1111-4111-8111-111111111111"
	b := "22222222-2222-4222-8222-222222222222"
	for _, id := range []string{a, b} {
		file := filepath.Join(root, "rollout-"+id+".jsonl")
		if err := os.WriteFile(file, []byte(`{"type":"session_meta","payload":{"cwd":"/same-project"}}`), 0600); err != nil {
			t.Fatal(err)
		}
	}
	other := filepath.Join(root, "rollout-"+b+".jsonl")
	if err := os.Chtimes(other, time.Now(), time.Now().Add(time.Hour)); err != nil {
		t.Fatal(err)
	}
	if got := providerTranscriptFile(root, "-"+a+".jsonl", false); got != filepath.Join(root, "rollout-"+a+".jsonl") {
		t.Fatalf("wrong provider: %q", got)
	}
	if got := providerTranscriptFile(root, "-missing.jsonl", false); got != "" {
		t.Fatalf("missing provider fell back: %q", got)
	}
	duplicate := filepath.Join(root, "duplicate")
	if err := os.Mkdir(duplicate, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(duplicate, "rollout-"+a+".jsonl"), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if got := providerTranscriptFile(root, "-"+a+".jsonl", false); got != "" {
		t.Fatalf("ambiguous provider: %q", got)
	}
}
func TestClaudeProviderTranscriptMatchesExactFilename(t *testing.T) {
	root := t.TempDir()
	id := "11111111-1111-4111-8111-111111111111"
	if err := os.WriteFile(filepath.Join(root, id+".jsonl"), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if got := providerTranscriptFile(root, id+".jsonl", true); got != filepath.Join(root, id+".jsonl") {
		t.Fatalf("wrong Claude file: %q", got)
	}
	if transcriptFileWithin(root, root+"-other/file.jsonl") || transcriptFileWithin(root, filepath.Join(root, "..", "foreign")) {
		t.Fatal("root escape accepted")
	}
}

func managedHistoryFixture(t *testing.T, executor string) (name, file, stateFile string) {
	t.Helper()
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	root := t.TempDir()
	for _, key := range []string{"HOME", "ROAMI_HOME", "ROAMI_DATA", "ROAM_HOME", "ROAM_DATA", "TTMUX_HOME", "TTMUX_DATA", "ROAMI_DATABASE_DIR", "ROAM_DATABASE_DIR", "TTMUX_DATABASE_DIR"} {
		t.Setenv(key, root)
	}
	name = "2026-1113-0900-abcd"
	provider := "11111111-1111-4111-8111-111111111111"
	pid := os.Getpid()
	stat, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		t.Skip("requires procfs")
	}
	token := strings.Fields(string(stat[strings.LastIndexByte(string(stat), ')')+1:]))[19]
	directory, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(root, "tmux-fixture")
	script := fmt.Sprintf("#!/bin/sh\ncase \"$1\" in\nlist-sessions) printf '$1\\t1794528000\\t%s\\thistory\\n';;\nlist-panes) printf '%s\\t$1\\t1794528000\\tfixture-server\\t%%%%1\\t%d\\t%s\\n';;\n*) exit 1;;\nesac\n", name, name, pid, directory)
	if err := os.WriteFile(bin, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMUX_BIN", bin)
	key := agentlifecycle.SessionResourceID(name, "$1", "1794528000", "fixture-server", "%1")
	stateFile = filepath.Join(root, "agents", "session-lifecycle", key, "state.json")
	state, err := json.Marshal(map[string]any{
		"executor": executor, "state": "unknown",
		"binding": map[string]any{
			"name": name, "tmuxId": "$1", "created": "1794528000", "server": "fixture-server", "pane": "%1",
			"pid": pid, "directory": directory, "providerConversationId": provider,
			"hostProof": agentlifecycle.HostProof(), "directoryProof": agentlifecycle.DirectoryProof(directory),
			"processes": map[string]string{strconv.Itoa(pid): token},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	file = filepath.Join(root, ".claude", "projects", "fixture", provider+".jsonl")
	if executor == "codex" {
		file = filepath.Join(root, ".codex", "sessions", "fixture", "rollout-"+provider+".jsonl")
	}
	for path, data := range map[string][]byte{
		stateFile: state,
		file:      []byte("{\"type\":\"assistant\",\"uuid\":\"existing-message\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"Existing history\"}]}}\n"),
	} {
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	if id, managed, err := agentlifecycle.SessionTranscriptProvider(runtime.New(), name, executor); err != nil || !managed || id != provider {
		t.Fatalf("fixture binding: %q %v %v", id, managed, err)
	}
	return name, file, stateFile
}

func TestUnknownManagedClaudeHistoryStaysReadable(t *testing.T) {
	name, file, stateFile := managedHistoryFixture(t, "claude")
	state, err := os.ReadFile(stateFile)
	if err != nil {
		t.Fatal(err)
	}
	r := gin.New()
	r.GET("/sessions/:name/transcript", (&API{}).ClaudeTranscript)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/sessions/"+name+"/transcript?tail=200&boff=1", nil))
	var result struct {
		Data struct {
			File     string `json:"file"`
			Messages []cMsg `json:"messages"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if w.Code != http.StatusOK || result.Data.File != file || len(result.Data.Messages) != 1 || result.Data.Messages[0].ID != "existing-message" {
		t.Fatalf("verified history was hidden: %d %s", w.Code, w.Body.String())
	}
	after, err := os.ReadFile(stateFile)
	if err != nil || string(after) != string(state) {
		t.Fatalf("history read changed execution state: %v", err)
	}
}

func TestManagedClaudeHistoryUsesConfiguredProfile(t *testing.T) {
	name, defaultFile, _ := managedHistoryFixture(t, "claude")
	config := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", config)
	dir := filepath.Join(config, "projects", "fixture")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(dir, filepath.Base(defaultFile))
	if err := os.WriteFile(file, []byte(`{"type":"assistant","uuid":"isolated","message":{"content":[{"type":"text","text":"Configured profile"}]}}`+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	r := gin.New()
	r.GET("/sessions/:name/transcript", (&API{}).ClaudeTranscript)
	path := "/sessions/" + name + "/transcript?boff=1"
	for _, suffix := range []string{"", "&file=" + file} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path+suffix, nil))
		if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), "Configured profile") || strings.Contains(w.Body.String(), "Existing history") {
			t.Fatalf("wrong configured profile: %d %s", w.Code, w.Body.String())
		}
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path+"&file="+defaultFile, nil))
	if w.Code != http.StatusBadRequest {
		t.Fatalf("other profile accepted: %d", w.Code)
	}
}

func TestNativeTranscriptMarksFinalAssistantText(t *testing.T) {
	for _, tt := range []struct {
		name string
		msg  *cMsg
		want bool
	}{
		{"claude final", parseLine(`{"type":"assistant","message":{"stop_reason":"end_turn","content":[{"type":"text","text":"Final"}]}}`), true},
		{"claude commentary", parseLine(`{"type":"assistant","message":{"stop_reason":"tool_use","content":[{"type":"text","text":"Interim"}]}}`), false},
		{"codex final", parseCodexItem(json.RawMessage(`{"type":"message","role":"assistant","phase":"final_answer","content":[{"text":"Final"}]}`), ""), true},
		{"codex commentary", parseCodexItem(json.RawMessage(`{"type":"message","role":"assistant","phase":"commentary","content":[{"text":"Interim"}]}`), ""), false},
	} {
		t.Run(tt.name, func(t *testing.T) {
			if tt.msg == nil || tt.msg.Final != tt.want {
				t.Fatalf("final marker mismatch: %+v", tt.msg)
			}
		})
	}
}
