package agentproxy

import (
	"encoding/json"
	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/modelgateway"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"
)

type capabilityTransport struct {
	standard, marketplace, models *http.Transport
}

func (t capabilityTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	if strings.HasPrefix(r.URL.Path, "/v1/model-gateway/") {
		return t.models.RoundTrip(r)
	}
	// Bundle downloads and MCP initialization exceed the ordinary API header budget.
	if strings.HasPrefix(r.URL.Path, "/v1/capability-markets") ||
		(strings.HasPrefix(r.URL.Path, "/v1/capability-imports/mcp/") && strings.HasSuffix(r.URL.Path, "/connect")) {
		return t.marketplace.RoundTrip(r)
	}
	return t.standard.RoundTrip(r)
}

// Proxy is mounted only under the existing authenticated API group.
func Proxy(socket string) http.Handler {
	target := &url.URL{Scheme: "http", Host: "roami-agent"}
	marketplace := agentruntime.Transport(socket)
	marketplace.ResponseHeaderTimeout = 100 * time.Second
	proxy := &httputil.ReverseProxy{
		Rewrite: func(r *httputil.ProxyRequest) {
			r.SetURL(target)
			r.Out.URL.Path = "/v1" + strings.TrimPrefix(r.In.URL.Path, "/api/agent")
			r.Out.URL.RawPath = ""
			for _, name := range []string{"X-Roami-Owner", "Authorization", "Cookie", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto"} {
				r.Out.Header.Del(name)
			}
			// Roami's current login is single-user; never accept identity from browser headers.
			r.Out.Header.Set("X-Roami-Owner", "local")
		},
		Transport: capabilityTransport{agentruntime.Transport(socket), marketplace, agentruntime.Transport(modelgateway.Socket(socket))}, FlushInterval: -1,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusServiceUnavailable)
			_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]string{"code": "AGENT_RUNTIME_UNAVAILABLE"}})
		},
	}
	return proxy
}
