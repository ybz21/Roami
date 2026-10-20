package agentinventory

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"
)

var claudeUsage = struct {
	sync.Mutex
	token [32]byte
	until time.Time
	quota AgentQuota
}{}

func claudeQuota(ctx context.Context) AgentQuota {
	token := os.Getenv("CLAUDE_CODE_OAUTH_TOKEN")
	if token == "" {
		home, _ := os.UserHomeDir()
		dir := os.Getenv("CLAUDE_CONFIG_DIR")
		if dir == "" {
			dir = filepath.Join(home, ".claude")
		}
		var credentials struct {
			OAuth struct {
				AccessToken string `json:"accessToken"`
				ExpiresAt   int64  `json:"expiresAt"`
			} `json:"claudeAiOauth"`
		}
		data, err := os.ReadFile(filepath.Join(dir, ".credentials.json"))
		if err != nil || json.Unmarshal(data, &credentials) != nil || credentials.OAuth.AccessToken == "" {
			return AgentQuota{State: "unknown", Reason: "login_required"}
		}
		if credentials.OAuth.ExpiresAt > 0 && credentials.OAuth.ExpiresAt <= time.Now().UnixMilli() {
			return AgentQuota{State: "unknown", Reason: "login_expired"}
		}
		token = credentials.OAuth.AccessToken
	}
	// The usage endpoint has a separate rate limit; UI polling must not multiply requests.
	claudeUsage.Lock()
	defer claudeUsage.Unlock()
	key := sha256.Sum256([]byte(token))
	if claudeUsage.token == key && time.Now().Before(claudeUsage.until) {
		return claudeUsage.quota
	}
	ctx, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	q := fetchClaudeQuota(ctx, http.DefaultClient, token, "https://api.anthropic.com/api/oauth/usage")
	if ctx.Err() == nil {
		claudeUsage.token, claudeUsage.until, claudeUsage.quota = key, time.Now().Add(5*time.Minute), q
	}
	return q
}

func fetchClaudeQuota(ctx context.Context, client *http.Client, token, endpoint string) AgentQuota {
	unknown := AgentQuota{State: "unknown", Reason: "request_failed"}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return unknown
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("anthropic-beta", "oauth-2025-04-20")
	// Never forward account credentials through a redirect.
	guarded := *client
	guarded.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	res, err := guarded.Do(req)
	if err != nil {
		return unknown
	}
	defer res.Body.Close()
	if res.StatusCode == http.StatusUnauthorized || res.StatusCode == http.StatusForbidden {
		unknown.Reason = "login_expired"
		return unknown
	}
	if res.StatusCode == http.StatusTooManyRequests {
		unknown.Reason = "rate_limited"
		return unknown
	}
	if res.StatusCode != http.StatusOK {
		return unknown
	}
	var body struct {
		FiveHour *claudeWindow `json:"five_hour"`
		SevenDay *claudeWindow `json:"seven_day"`
	}
	if json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(&body) != nil {
		return unknown
	}
	windows := []quotaWindow{}
	for i, window := range []*claudeWindow{body.FiveHour, body.SevenDay} {
		if window == nil || window.Utilization == nil {
			continue
		}
		reset, err := time.Parse(time.RFC3339Nano, window.ResetsAt)
		if err != nil || !reset.After(time.Now()) {
			continue
		}
		minutes := 300
		if i == 1 {
			minutes = 10080
		}
		windows = append(windows, quotaWindow{Remaining: max(0, min(100, 100-*window.Utilization)), WindowMin: minutes, ResetsAt: reset.Unix()})
	}
	if len(windows) == 0 {
		unknown.Reason = "no_snapshot"
		return unknown
	}
	remaining := windows[0].Remaining
	return AgentQuota{State: "available", Remaining: &remaining, Windows: windows, ObservedAt: time.Now().UTC().Format(time.RFC3339), Source: "Claude usage"}
}

type claudeWindow struct {
	Utilization *float64 `json:"utilization"`
	ResetsAt    string   `json:"resets_at"`
}
