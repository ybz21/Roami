package modelgateway

import (
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestGatewayLANAcceptsExternalKeysAndBothProtocols(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" || r.Header.Get("Authorization") != "Bearer upstream-secret" {
			t.Error("gateway did not use the configured OpenAI upstream")
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"fixture-answer","model":"fixture","choices":[{"index":0,"message":{"role":"assistant","content":"answer"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL+"/v1", "openai-completions")
	const key = "fixture-external-lan-key"
	if w := setAccessKey(t, h, http.MethodPut, key, h.Catalog.value.Revision); w.Code != http.StatusOK {
		t.Fatalf("set external key: %d %s", w.Code, w.Body)
	}
	request := func(method, path, remote, header, credential, body string) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.RemoteAddr = remote
		r.Header.Set(header, credential)
		w := httptest.NewRecorder()
		h.serveGatewayLAN(w, r)
		return w
	}
	lan := "192.168.12.3:12345"
	if w := request(http.MethodGet, "/v1/models", lan, "Authorization", "Bearer "+key, ""); w.Code != http.StatusUnauthorized {
		t.Fatalf("LAN request while disabled: %d", w.Code)
	}
	next := h.Catalog.snapshot()
	next.LANEnabled = true
	if err := h.Catalog.persist(next); err != nil {
		t.Fatal(err)
	}
	reopened, err := openCatalog(h.Ledger)
	if err != nil || !reopened.value.LANEnabled {
		t.Fatalf("LAN setting did not persist: %v", err)
	}
	h.Catalog = reopened
	for _, credential := range []string{"", h.Catalog.credential("roami")} {
		if w := request(http.MethodGet, "/v1/models", lan, "Authorization", "Bearer "+credential, ""); w.Code != http.StatusUnauthorized {
			t.Fatalf("invalid external login accepted: %d", w.Code)
		}
	}
	if w := request(http.MethodGet, "/v1/models", "203.0.113.42:12345", "Authorization", "Bearer "+key, ""); w.Code != http.StatusForbidden {
		t.Fatalf("non-LAN request accepted: %d", w.Code)
	}
	if w := request(http.MethodGet, "/v1/model-gateway/network", lan, "Authorization", "Bearer "+key, ""); w.Code != http.StatusNotFound {
		t.Fatalf("private route exposed: %d", w.Code)
	}
	body := `{"model":"coding-main","max_tokens":64,"messages":[{"role":"user","content":"hello"}]}`
	for _, tc := range []struct{ path, header, value, needle string }{
		{"/v1/chat/completions", "Authorization", "Bearer " + key, `"choices"`},
		{"/v1/messages", "X-Api-Key", key, `"type":"message"`},
	} {
		if w := request(http.MethodPost, tc.path, lan, tc.header, tc.value, body); w.Code != http.StatusOK || !strings.Contains(w.Body.String(), tc.needle) || !strings.Contains(w.Body.String(), "answer") {
			t.Fatalf("LAN protocol %s: %d %s", tc.path, w.Code, w.Body)
		}
	}
}

func TestGatewayNetworkToggleBindsAndClosesLANAddresses(t *testing.T) {
	if len(gatewayLANAddresses()) == 0 {
		t.Skip("host has no private IPv4 interface")
	}
	hostListener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer hostListener.Close()
	h := catalogHandler(t, "https://models.example/v1", "openai-completions")
	h.Catalog.value.Port = hostListener.Addr().(*net.TCPAddr).Port
	toggle := func(body string) *httptest.ResponseRecorder {
		t.Helper()
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodPut, "/v1/model-gateway/network", strings.NewReader(body)))
		return w
	}
	if w := toggle(`{"enabled":true}`); w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"enabled":true`) || h.lan == nil || len(h.lan.urls) == 0 {
		t.Fatalf("enable network: %d %s", w.Code, w.Body)
	}
	lan := h.lan
	t.Cleanup(lan.close)
	if w := toggle(`{"enabled":false}`); w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"enabled":false`) || h.lan != nil || h.Catalog.value.LANEnabled {
		t.Fatalf("disable network: %d %s", w.Code, w.Body)
	}
	for _, address := range lan.urls {
		if listener, err := net.Listen("tcp4", strings.TrimPrefix(address, "http://")); err != nil {
			t.Fatalf("LAN address remained open: %v", err)
		} else {
			_ = listener.Close()
		}
	}
}
