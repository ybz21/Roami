package main

import (
	"encoding/json"
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

func TestProjectProvisionCLIAllowsNameWithoutExistingDirectory(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/projects" || r.Method != "POST" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		if body["dir"] != "" || body["displayName"] != "New App" || body["provisionKey"] != "stable-key" || body["baseDir"] != "/projects" {
			t.Errorf("wrong provisioning request: %v", body)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":{"key":"project-id","dir":"/projects/New App","created":true}}`))
	}))
	defer server.Close()
	t.Setenv("ROAMI_HOME", t.TempDir())
	if code := runAPICommand("project", []string{"create", "--name", "New App", "--provision-key", "stable-key", "--base-dir", "/projects", "--json", "--server", server.URL}); code != 0 {
		t.Fatalf("create exit=%d", code)
	}
}

func TestProjectSessionsUsesCompleteMembershipQuery(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/projects" || r.URL.Query().Get("sessionProject") != "p & 1" {
			t.Errorf("unexpected membership query: %s", r.URL)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"projectId":"p & 1","sessions":[{"name":"s4","label":"Fourth Codex","agent":"codex"}]}}`))
	}))
	defer server.Close()
	t.Setenv("ROAMI_HOME", t.TempDir())
	if code := runAPICommand("project", []string{"sessions", "p & 1", "--json", "--server", server.URL}); code != 0 {
		t.Fatalf("sessions exit=%d", code)
	}
}
