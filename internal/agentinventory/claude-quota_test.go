package agentinventory

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestClaudeQuotaRequiresValidLocalLogin(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", dir)
	t.Setenv("CLAUDE_CODE_OAUTH_TOKEN", "")
	if q := claudeQuota(context.Background()); q.Reason != "login_required" {
		t.Fatalf("missing credentials: %+v", q)
	}
	data := fmt.Sprintf(`{"claudeAiOauth":{"accessToken":"expired","expiresAt":%d}}`, time.Now().Add(-time.Hour).UnixMilli())
	if err := os.WriteFile(filepath.Join(dir, ".credentials.json"), []byte(data), 0o600); err != nil {
		t.Fatal(err)
	}
	if q := claudeQuota(context.Background()); q.Reason != "login_expired" {
		t.Fatalf("expired credentials: %+v", q)
	}
}

func TestClaudeQuotaWindowsAndErrors(t *testing.T) {
	for _, tc := range []struct {
		name         string
		code         int
		body, reason string
	}{
		{"available", 200, fmt.Sprintf(`{"five_hour":{"utilization":100,"resets_at":%q},"seven_day":{"utilization":42,"resets_at":%q}}`, time.Now().Add(time.Hour).UTC().Format(time.RFC3339), time.Now().Add(24*time.Hour).UTC().Format(time.RFC3339)), ""},
		{"signed out", 401, `{}`, "login_expired"},
		{"throttled", 429, `{}`, "rate_limited"},
		{"unavailable", 500, `{}`, "request_failed"},
		{"malformed", 200, `{`, "request_failed"},
		{"null windows", 200, `{"five_hour":null,"seven_day":null}`, "no_snapshot"},
		{"missing utilization", 200, fmt.Sprintf(`{"five_hour":{"resets_at":%q}}`, time.Now().Add(time.Hour).UTC().Format(time.RFC3339)), "no_snapshot"},
		{"expired", 200, `{"five_hour":{"utilization":20,"resets_at":"2020-01-01T00:00:00Z"}}`, "no_snapshot"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "Bearer local-test" || r.Header.Get("anthropic-beta") != "oauth-2025-04-20" {
					t.Error("missing usage authentication headers")
				}
				w.WriteHeader(tc.code)
				fmt.Fprint(w, tc.body)
			}))
			defer srv.Close()
			q := fetchClaudeQuota(context.Background(), srv.Client(), "local-test", srv.URL)
			if tc.reason != "" {
				if q.State != "unknown" || q.Reason != tc.reason {
					t.Fatalf("unexpected failure: %+v", q)
				}
			} else if q.State != "available" || len(q.Windows) != 2 || q.Windows[0].Remaining != 0 || q.Windows[1].Remaining != 58 || q.Windows[1].WindowMin != 10080 {
				t.Fatalf("unexpected quota: %+v", q)
			}
		})
	}
}

func TestClaudeQuotaDoesNotFollowRedirect(t *testing.T) {
	called := false
	destination := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true }))
	defer destination.Close()
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, destination.URL, http.StatusFound) }))
	defer source.Close()
	q := fetchClaudeQuota(context.Background(), source.Client(), "local-test", source.URL)
	if called || q.State != "unknown" {
		t.Fatal("followed usage redirect")
	}
}
