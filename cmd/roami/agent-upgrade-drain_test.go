package main

import (
	"encoding/json"
	"net"
	"net/http"
	"path/filepath"
	"reflect"
	"sync"
	"testing"

	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
)

func TestAgentUpgradeDrain(t *testing.T) {
	for _, tc := range []struct {
		name           string
		legacy         bool
		busy           bool
		invalidReceipt bool
		want           []string
	}{
		{name: "ready", want: []string{"begin", "agent-pause", "status", "status", "resume", "agent-resume"}},
		{name: "busy", busy: true, want: []string{"begin", "agent-pause", "resume", "agent-resume"}},
		{name: "incomplete", invalidReceipt: true, want: []string{"begin", "agent-pause", "status", "resume", "agent-resume"}},
		{name: "legacy", legacy: true, want: []string{"begin", "agent-pause", "resume", "agent-resume"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			socket := filepath.Join(t.TempDir(), "agent-fixture.sock")
			callOrder := make(chan string, len(tc.want)+4)
			startUpgradeTestSocket(t, socket, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var body struct{ Resume bool }
				if r.URL.Path != "/internal/installation/quiesce" || json.NewDecoder(r.Body).Decode(&body) != nil {
					t.Error("invalid Agent pause request")
					w.WriteHeader(http.StatusBadRequest)
					return
				}
				if body.Resume {
					callOrder <- "agent-resume"
				} else {
					callOrder <- "agent-pause"
					if tc.busy {
						w.WriteHeader(http.StatusConflict)
						return
					}
				}
				httpapi.WriteJSON(w, http.StatusOK, map[string]bool{"ok": true})
			}))
			var mu sync.Mutex
			lease := ""
			statusChecks := 0
			startUpgradeTestSocket(t, httpapi.Socket(socket), http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var body httpapi.UpgradeRequest
				if r.URL.Path != httpapi.UpgradePath || json.NewDecoder(r.Body).Decode(&body) != nil {
					t.Error("invalid gateway pause request")
					w.WriteHeader(http.StatusBadRequest)
					return
				}
				callOrder <- body.Action
				if tc.legacy {
					httpapi.Reject(w, http.StatusNotFound, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
					return
				}
				mu.Lock()
				defer mu.Unlock()
				active := 0
				switch body.Action {
				case "begin":
					lease = body.Lease
					if lease == "" {
						t.Error("upgrade admission needs an ownership lease")
					}
				case "status":
					if tc.invalidReceipt {
						httpapi.WriteJSON(w, http.StatusOK, map[string]any{"data": map[string]bool{"ready": true}})
						return
					}
					if body.Lease != lease {
						t.Error("status polled a different lease")
					}
					statusChecks++
					if statusChecks == 1 {
						active = 1
					}
				case "resume":
					if (tc.busy || tc.invalidReceipt) && body.Lease != lease {
						t.Error("failed preparation did not release its own lease")
					}
				}
				httpapi.WriteJSON(w, http.StatusOK, map[string]any{"data": httpapi.UpgradeState{Active: active}})
			}))

			err := prepareAgentUpgrade(socket, false)
			if (err != nil) != (tc.busy || tc.invalidReceipt) {
				t.Fatalf("unexpected preparation result: %v", err)
			}
			if !tc.busy && !tc.invalidReceipt {
				if err := prepareAgentUpgrade(socket, true); err != nil {
					t.Fatal(err)
				}
			}
			close(callOrder)
			var got []string
			for item := range callOrder {
				got = append(got, item)
			}
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("calls = %v, want %v", got, tc.want)
			}
		})
	}
}

func startUpgradeTestSocket(t *testing.T, path string, handler http.Handler) {
	t.Helper()
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: handler}
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(func() {
		_ = server.Close()
		_ = listener.Close()
	})
}
