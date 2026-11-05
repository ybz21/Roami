package main

import (
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAgentHistoryPaginationPreservesCursorAndBranchIdentity(t *testing.T) {
	raw, err := agentHistoryPath("original-main", 20, "cursor&branch=foreign", "original-branch")
	if err != nil {
		t.Fatal(err)
	}
	u, err := url.Parse(raw)
	if err != nil || u.Path != "/v1/conversations/original-main/messages" || u.Query().Get("before") != "cursor&branch=foreign" || u.Query().Get("branch") != "original-branch" || u.Query().Get("limit") != "20" {
		t.Fatal(raw, err)
	}
	for _, limit := range []int{0, 101, -1} {
		if _, err = agentHistoryPath("main", limit, "", ""); err == nil {
			t.Fatal("invalid page size accepted", limit)
		}
	}
}

func TestAgentRequestRejectsOverflowWithoutPartialSuccessJSON(t *testing.T) {
	dir, err := os.MkdirTemp("/tmp", "okr-http-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(dir)
	socket := filepath.Join(dir, "runtime.sock")
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/large" {
			_, _ = w.Write([]byte(`{"text":"` + strings.Repeat("x", 4<<20) + `"}`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"page":{"hasMore":true,"olderCursor":"original"}}}`))
	})}
	defer server.Close()
	go server.Serve(listener)
	raw, err := agentRequest(socket, "GET", "/large", nil)
	if err == nil || len(raw) != 0 || !strings.Contains(err.Error(), "AGENT_RESPONSE_TOO_LARGE") {
		t.Fatal(len(raw), err)
	}
	raw, err = agentRequest(socket, "GET", "/page", nil)
	if err != nil || !strings.Contains(string(raw), `"olderCursor":"original"`) {
		t.Fatal(string(raw), err)
	}
}
