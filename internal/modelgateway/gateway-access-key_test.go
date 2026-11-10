package modelgateway

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func setAccessKey(t *testing.T, h *Handler, method, key, revision string) *httptest.ResponseRecorder {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"revision": revision, "apiKey": key})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(method, "/v1/model-gateway/access-key", strings.NewReader(string(body))))
	return w
}

func TestGatewayAccessKeyPersistsWithoutExposingOrChangingAgentCredentials(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer upstream-secret" {
			t.Error("client key leaked upstream")
		}
		_, _ = io.WriteString(w, `{"choices":[{"message":{"role":"assistant","content":"ok"}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	const first = "fixture-gateway-access-one"
	const second = "fixture-gateway-access-two"
	agentKey := h.Catalog.credential("opencode")
	if w := requestWithKey(h, first, "/v1/models", ""); w.Code != 401 {
		t.Fatalf("unconfigured key accepted: %d", w.Code)
	}
	if w := setAccessKey(t, h, "PUT", first, h.Catalog.value.Revision); w.Code != 200 || strings.Contains(w.Body.String(), first) {
		t.Fatalf("configure: %d %s", w.Code, w.Body)
	}
	reloaded, err := openCatalog(h.Ledger)
	if err != nil {
		t.Fatal(err)
	}
	h.Catalog = reloaded
	var stored string
	if err = h.Ledger.db.QueryRow(`SELECT value FROM gateway_catalog WHERE id=1`).Scan(&stored); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(stored, first) {
		t.Fatal("plaintext client key persisted")
	}
	if h.Catalog.credential("opencode") != agentKey {
		t.Fatal("agent credential changed")
	}
	if w := requestWithKey(h, first, "/v1/models", ""); w.Code != 200 {
		t.Fatalf("models: %d %s", w.Code, w.Body)
	}
	payload := `{"model":"coding-main","messages":[{"role":"user","content":"fixture"}]}`
	if w := requestWithKey(h, first, "/v1/chat/completions", payload); w.Code != 200 {
		t.Fatalf("inference: %d %s", w.Code, w.Body)
	}
	stats, err := h.Ledger.StatisticsForSource(1, "", "", "external")
	if err != nil || len(stats.Recent) != 1 || stats.Recent[0].AgentKind != "external" {
		t.Fatalf("attribution: %+v %v", stats, err)
	}
	oldID := h.Catalog.value.AccessKey.ID
	if w := setAccessKey(t, h, "PUT", second, h.Catalog.value.Revision); w.Code != 200 {
		t.Fatal(w.Body)
	}
	if h.Catalog.keyAllowed("external", oldID) {
		t.Fatal("previous key still admitted")
	}
	if w := requestWithKey(h, first, "/v1/models", ""); w.Code != 401 {
		t.Fatal("previous key authenticated")
	}
	next := h.Catalog.snapshot()
	if err = h.Catalog.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	if w := requestWithKey(h, second, "/v1/models", ""); w.Code != 200 {
		t.Fatal("catalog update discarded access key")
	}
	if w := requestWithKey(h, second, "/v1/model-gateway/access-key", ""); w.Code != 404 {
		t.Fatal("client key reached management")
	}
	if w := setAccessKey(t, h, "DELETE", "", h.Catalog.value.Revision); w.Code != 200 {
		t.Fatal(w.Body)
	}
	if w := requestWithKey(h, second, "/v1/models", ""); w.Code != 401 {
		t.Fatal("disabled key authenticated")
	}
	if w := requestWithKey(h, agentKey, "/v1/models", ""); w.Code != 200 {
		t.Fatal("disabling client key affected agent key")
	}
}

func TestGatewayAccessKeyRejectsInvalidStaleAndAgentKeys(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-completions")
	before := h.Catalog.value.Revision
	for _, key := range []string{"short", strings.Repeat("a", 513), "fixture-gateway-key\n", "fixture gateway key", h.Catalog.credential("opencode")} {
		if w := setAccessKey(t, h, "PUT", key, before); w.Code != 400 {
			t.Fatalf("invalid key: %d", w.Code)
		}
	}
	if w := setAccessKey(t, h, "PUT", "fixture-gateway-access", "stale"); w.Code != 409 {
		t.Fatalf("stale write: %d", w.Code)
	}
	if before != h.Catalog.value.Revision || h.Catalog.value.AccessKey.Hash != "" {
		t.Fatal("invalid write changed key")
	}
}

func TestGatewayAccessKeyRevocationWakesQueuedClient(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-release
		_, _ = io.WriteString(w, `{"usage":{"prompt_tokens":1,"completion_tokens":1}}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	limit := 100.0
	_ = h.Ledger.Configure(testConfiguration(&limit))
	key := "fixture-gateway-queued-access"
	if w := setAccessKey(t, h, "PUT", key, h.Catalog.value.Revision); w.Code != 200 {
		t.Fatal(w.Body)
	}
	body := `{"model":"coding-main","messages":[{"role":"user","content":"fixture"}]}`
	first := make(chan *httptest.ResponseRecorder, 1)
	go func() { first <- requestWithKey(h, key, "/v1/chat/completions", body) }()
	<-entered
	queued := make(chan *httptest.ResponseRecorder, 1)
	go func() { queued <- requestWithKey(h, key, "/v1/chat/completions", body) }()
	deadline := time.Now().Add(time.Second)
	waiting := false
	for time.Now().Before(deadline) {
		h.mu.Lock()
		waiting = len(h.admissionQueue) > 0
		h.mu.Unlock()
		if waiting {
			break
		}
		time.Sleep(time.Millisecond)
	}
	if !waiting {
		close(release)
		t.Fatal("second request did not wait on admission")
	}
	if w := setAccessKey(t, h, "DELETE", "", h.Catalog.value.Revision); w.Code != 200 {
		close(release)
		t.Fatal(w.Body)
	}
	select {
	case w := <-queued:
		if w.Code != 401 {
			close(release)
			t.Fatalf("queued request was not revoked: %d", w.Code)
		}
	case <-time.After(time.Second):
		close(release)
		t.Fatal("revocation did not wake admission")
	}
	close(release)
	if w := <-first; w.Code != 200 {
		t.Fatalf("admitted call was interrupted: %d", w.Code)
	}
}
