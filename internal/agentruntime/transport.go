package agentruntime

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"
)

func Transport(socket string) *http.Transport {
	return &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, "unix", socket)
	}, ResponseHeaderTimeout: 15 * time.Second}
}

// Proxy is mounted only under the existing authenticated API group.
func Proxy(socket string) http.Handler {
	target := &url.URL{Scheme: "http", Host: "roami-agent"}
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
		Transport: Transport(socket), FlushInterval: -1,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusServiceUnavailable)
			_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]string{"code": "AGENT_RUNTIME_UNAVAILABLE"}})
		},
	}
	return proxy
}
