package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestProjectOKRRevisionConflictIsNotReplayed(t *testing.T) {
	t.Setenv("ROAMI_HOME", t.TempDir())
	input := filepath.Join(t.TempDir(), "review.json")
	if err := os.WriteFile(input, []byte(`{"revision":7,"summary":"observed decline","actions":"test opening"}`), 0600); err != nil {
		t.Fatal(err)
	}
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != "POST" || r.URL.Path != "/api/projects/p & 1/okr/reviews" {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		var payload struct{ Revision int }
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil || payload.Revision != 7 {
			t.Errorf("lost revision: %+v %v", payload, err)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"error":"OKR_REVISION_CONFLICT"}`))
	}))
	defer server.Close()
	if code := runAPICommand("project", []string{"okr", "review", "p & 1", "--file", input, "--server", server.URL, "--json"}); code == 0 {
		t.Fatal("conflict reported as success")
	}
	if calls != 1 {
		t.Fatalf("conflicting write replayed %d times", calls)
	}
}

func TestProjectOKRRejectsMalformedOrMissingWriteInput(t *testing.T) {
	t.Setenv("ROAMI_HOME", t.TempDir())
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("invalid local input reached server")
	}))
	defer server.Close()
	for _, content := range []string{"[]", `{"revision":1} {"revision":2}`, ""} {
		input := filepath.Join(t.TempDir(), "input.json")
		if err := os.WriteFile(input, []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
		if code := runProjectOKR([]string{"save", "p1", "--file", input, "--server", server.URL}); code == 0 {
			t.Fatal("invalid JSON accepted:", content)
		}
	}
	if code := runProjectOKR([]string{"collect", "p1", "--server", server.URL}); code == 0 {
		t.Fatal("write without revision input accepted")
	}
}

func TestProjectOKRSyncAndMemoryCommands(t *testing.T) {
	t.Setenv("ROAMI_HOME", t.TempDir())
	for _, tc := range []struct{ action, method, suffix, body string }{{"sync", "POST", "/sync", `{"revision":4}`}, {"memory", "PUT", "/memory", `{"content":"team","expectedSha256":"abc"}`}} {
		t.Run(tc.action, func(t *testing.T) {
			input := filepath.Join(t.TempDir(), "input.json")
			if err := os.WriteFile(input, []byte(tc.body), 0600); err != nil {
				t.Fatal(err)
			}
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Method != tc.method || r.URL.Path != "/api/projects/project/okr"+tc.suffix {
					t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
				}
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(`{"data":{"revision":5}}`))
			}))
			defer server.Close()
			if code := runProjectOKR([]string{tc.action, "project", "--file", input, "--server", server.URL, "--json"}); code != 0 || calls != 1 {
				t.Fatal(code, calls)
			}
		})
	}
}
