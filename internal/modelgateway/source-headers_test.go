package modelgateway

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestModelSourceHeadersApplyToDiscoveryAndInference(t *testing.T) {
	const headerValue = "fixture-gateway-user"
	var discovery, inference atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-User-ID") != headerValue || r.Header.Get("Authorization") != "Bearer upstream-secret" {
			w.WriteHeader(http.StatusForbidden)
			return
		}
		switch r.URL.Path {
		case "/v1/models":
			discovery.Add(1)
		case "/v1/responses":
			inference.Add(1)
		}
		sourceTransportFixture(w, r)
	}))
	defer upstream.Close()

	h := catalogHandler(t, upstream.URL+"/v1", "openai-responses")
	ctx := context.Background()
	view := h.Catalog.view(ctx)
	view.Sources[0].Headers = map[string]string{"x-user-id": headerValue}
	if w := discoverRequest(h, view.Sources[0], view.Revision); w.Code != http.StatusOK || strings.Contains(w.Body.String(), headerValue) {
		t.Fatalf("draft discovery: %d %s", w.Code, w.Body)
	}
	if len(h.Catalog.value.Sources[0].Headers) != 0 {
		t.Fatal("draft discovery saved headers")
	}
	save := func(value any) *httptest.ResponseRecorder {
		t.Helper()
		raw, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodPut, "/v1/model-gateway/catalog", strings.NewReader(string(raw))))
		if w.Code != http.StatusOK || strings.Contains(w.Body.String(), headerValue) {
			t.Fatalf("catalog response: %d %s", w.Code, w.Body)
		}
		return w
	}
	if w := save(view); !strings.Contains(w.Body.String(), `"headerNames":["X-User-Id"]`) {
		t.Fatalf("catalog response missing header name: %s", w.Body)
	}
	reopened, err := openCatalog(h.Ledger)
	if err != nil {
		t.Fatal(err)
	}
	h.Catalog = reopened
	saved := h.Catalog.view(ctx)
	if w := discoverRequest(h, saved.Sources[0], saved.Revision); w.Code != http.StatusOK {
		t.Fatalf("saved discovery: %d %s", w.Code, w.Body)
	}
	call := func() *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(`{"model":"coding-main","input":"hello"}`))
		req.Header.Set("Authorization", "Bearer "+h.Catalog.credential("codex"))
		req.Header.Set("X-User-ID", "caller-value")
		w := httptest.NewRecorder()
		h.publicModels(w, req)
		return w
	}
	save(saved)
	if w := call(); w.Code != http.StatusOK || discovery.Load() != 2 || inference.Load() != 1 {
		t.Fatalf("inference: %d %s (discovery=%d, inference=%d)", w.Code, w.Body, discovery.Load(), inference.Load())
	}
	saved = h.Catalog.view(ctx)
	raw, _ := json.Marshal(saved.Sources[0])
	var source map[string]any
	if err := json.Unmarshal(raw, &source); err != nil {
		t.Fatal(err)
	}
	source["headers"] = map[string]string{}
	save(map[string]any{"revision": saved.Revision, "sources": []any{source}, "models": saved.Models})
	if len(h.Catalog.value.Sources[0].Headers) != 0 {
		t.Fatal("explicit empty header map did not remove saved headers")
	}
}

func TestModelSourceHeadersRejectInvalidValuesAndProtectSavedEndpoint(t *testing.T) {
	h := catalogHandler(t, "https://saved.example/v1", "openai-responses")
	saved := h.Catalog.snapshot()
	saved.Sources[0].Headers = map[string]string{"X-User-ID": "saved-fixture-user"}
	if err := h.Catalog.update(context.Background(), saved); err != nil {
		t.Fatal(err)
	}
	view := h.Catalog.view(context.Background())
	for _, headers := range []map[string]string{
		{"Authorization": "unsupported"},
		{"X-Api-Key": "unsupported"},
		{"Host": "other.example"},
		{"Transfer-Encoding": "chunked"},
		{"X-Roami-Owner": "unsupported"},
		{"X Header": "bad"},
		{"X-User-ID": "a", "x-user-id": "b"},
		{"X-User-ID": "a\r\nX-Injected: b"},
		{"X-New": ""},
	} {
		source := view.Sources[0]
		source.Headers = headers
		if w := discoverRequest(h, source, view.Revision); w.Code != http.StatusBadRequest || !strings.Contains(w.Body.String(), "INVALID_MODEL_SOURCE_HEADERS") {
			t.Fatalf("invalid headers accepted: %v, response %d %s", headers, w.Code, w.Body)
		}
	}
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if r.Header.Get("X-User-ID") != "replacement-fixture-user" {
			t.Error("changed endpoint received the wrong source header")
		}
		_, _ = io.WriteString(w, `{"data":[{"id":"fixture"}]}`)
	}))
	defer upstream.Close()
	source := view.Sources[0]
	source.BaseURL, source.APIKey = upstream.URL+"/v1", "replacement-key"
	for _, headers := range []map[string]string{nil, {"X-User-ID": ""}} {
		source.Headers = headers
		if w := discoverRequest(h, source, view.Revision); w.Code != http.StatusBadRequest || !strings.Contains(w.Body.String(), "MODEL_HEADERS_REQUIRED_FOR_ENDPOINT") {
			t.Fatalf("changed endpoint reused saved header: %d %s", w.Code, w.Body)
		}
	}
	if hits.Load() != 0 {
		t.Fatal("a request reached the changed endpoint before headers were replaced")
	}
	source.Headers = map[string]string{"X-User-ID": "replacement-fixture-user"}
	if w := discoverRequest(h, source, view.Revision); w.Code != http.StatusOK || hits.Load() != 1 {
		t.Fatalf("replacement headers: %d %s", w.Code, w.Body)
	}
}
