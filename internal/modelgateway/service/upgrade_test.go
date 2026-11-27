package service

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
)

func TestGatewayUpgradeWaitsForAcceptedInference(t *testing.T) {
	entered := make(chan struct{})
	release := make(chan struct{})
	var completed sync.Once
	finish := func() { completed.Do(func() { close(release) }) }
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		select {
		case <-release:
			fmt.Fprint(w, `{"choices":[{"message":{"role":"assistant","content":"finished"}}],"usage":{"prompt_tokens":4,"completion_tokens":1}}`)
		case <-r.Context().Done():
		}
	}))
	defer upstream.Close()
	defer finish()

	gateway := catalogHandler(t, upstream.URL, "openai-completions")
	apiKey := gateway.Catalog.credential("roami")
	public := func(method, path string) *httptest.ResponseRecorder {
		response := httptest.NewRecorder()
		request := httptest.NewRequest(method, path, strings.NewReader(`{"model":"coding-main","messages":[{"role":"user","content":"hello"}]}`))
		request.Header.Set("Authorization", "Bearer "+apiKey)
		gateway.publicModels(response, request)
		return response
	}
	upgrade := func(action, lease string, want int, active int) {
		t.Helper()
		body, err := json.Marshal(httpapi.UpgradeRequest{Action: action, Lease: lease})
		if err != nil {
			t.Fatal(err)
		}
		response := httptest.NewRecorder()
		gateway.ServeHTTP(response, httptest.NewRequest("POST", httpapi.UpgradePath, bytes.NewReader(body)))
		if response.Code != want {
			t.Fatalf("%s: got HTTP %d, want %d, body: %s", action, response.Code, want, response.Body)
		}
		if want == http.StatusOK {
			var envelope struct {
				Data httpapi.UpgradeState `json:"data"`
			}
			if err := json.Unmarshal(response.Body.Bytes(), &envelope); err != nil || envelope.Data.Active != active {
				t.Fatalf("%s: want %d active, got %s (%v)", action, active, response.Body, err)
			}
		}
	}

	outcome := make(chan *httptest.ResponseRecorder, 1)
	go func() { outcome <- public("POST", "/v1/chat/completions") }()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("inference did not reach the upstream")
	}

	upgrade("begin", "first", http.StatusOK, 1)
	upgrade("begin", "second", http.StatusConflict, 0)
	upgrade("status", "first", http.StatusOK, 1)
	upgrade("resume", "second", http.StatusOK, 1)
	if discovery := public("GET", "/v1/models"); discovery.Code != http.StatusOK {
		t.Fatalf("model discovery unavailable during drain: %d", discovery.Code)
	}
	if management := public("POST", httpapi.UpgradePath); management.Code != http.StatusNotFound {
		t.Fatalf("public listener exposed upgrade controls: %d", management.Code)
	}
	rejected := public("POST", "/v1/chat/completions")
	foundation := httptest.NewRecorder()
	gateway.ServeHTTP(foundation, httptest.NewRequest("POST", "/v1/chat/completions", nil))
	for _, response := range []*httptest.ResponseRecorder{rejected, foundation} {
		if response.Code != http.StatusServiceUnavailable || response.Header().Get("Retry-After") != "5" ||
			response.Header().Get("X-Roami-Model-Error") != "MODEL_GATEWAY_UPGRADING" {
			t.Fatalf("new inference was not deferred: %d %s", response.Code, response.Body)
		}
	}

	finish()
	select {
	case completed := <-outcome:
		if completed.Code != http.StatusOK || !strings.Contains(completed.Body.String(), "finished") {
			t.Fatalf("accepted inference was interrupted: %d %s", completed.Code, completed.Body)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("accepted inference did not finish")
	}
	upgrade("status", "first", http.StatusOK, 0)
	upgrade("resume", "first", http.StatusOK, 0)
	upgrade("status", "first", http.StatusConflict, 0)
}

func TestGatewayUpgradeAdmissionExpires(t *testing.T) {
	gateway := NewHandler(nil)
	gateway.upgrade.lease = "expired"
	gateway.upgrade.expires = time.Now().Add(-time.Second)
	if !gateway.beginModelRequest(httptest.NewRecorder()) {
		t.Fatal("an abandoned installation still holds admission closed")
	}
	gateway.finishModelRequest()
}
