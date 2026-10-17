package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestProjectShowUsesProjectsEnvelope(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path != "/api/projects" {
			t.Errorf("path=%s", r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"data":{"projects":[{"key":"p1","name":"project"}],"loose":[]}}`))
	}))
	defer server.Close()
	t.Setenv("ROAMI_HOME", t.TempDir())
	if code := runAPICommand("project", []string{"show", "p1", "--json", "--server", server.URL}); code != 0 {
		t.Fatalf("show exit=%d", code)
	}
}
func TestAPIClientDoesNotFollowCredentialRedirect(t *testing.T) {
	destination := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Error("followed cross-origin redirect") }))
	defer destination.Close()
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, destination.URL, http.StatusTemporaryRedirect)
	}))
	defer origin.Close()
	t.Setenv("ROAMI_HOME", t.TempDir())
	client, e := connectAPI(origin.URL)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = client.request("POST", "/api/login", map[string]string{"password": "test"}); e == nil {
		t.Fatal("redirect reported as success")
	}
}
