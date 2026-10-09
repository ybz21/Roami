package agentdiscovery

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"ttmux-cli-go/pkg/plugin/sdk"
)

type quota struct {
	Remaining  *float64      `json:"remainingPercent,omitempty"`
	WindowMin  int           `json:"windowMinutes,omitempty"`
	ResetsAt   int64         `json:"resetsAt,omitempty"`
	ObservedAt string        `json:"observedAt,omitempty"`
	Source     string        `json:"source,omitempty"`
	State      string        `json:"state"`
	Windows    []quotaWindow `json:"windows,omitempty"`
}

type quotaWindow struct {
	Remaining float64 `json:"remainingPercent"`
	WindowMin int     `json:"windowMinutes"`
	ResetsAt  int64   `json:"resetsAt,omitempty"`
}

type entry struct {
	Kind      string `json:"kind"`
	Installed bool   `json:"installed"`
	Quota     quota  `json:"quota"`
}

var packages = map[string]string{
	"claude":   "@anthropic-ai/claude-code",
	"codex":    "@openai/codex",
	"pi":       "@earendil-works/pi-coding-agent",
	"opencode": "opencode-ai",
}

func Activate(*sdk.Ctx) sdk.Plugin {
	return sdk.Plugin{Commands: map[string]sdk.CommandHandler{"scan": scan, "install": install}}
}

func scan(ctx *sdk.Ctx, _ map[string]string) (any, error) {
	providers, err := ctx.AgentProviders()
	if err != nil {
		return nil, err
	}
	rows := make([]entry, 0, len(providers))
	kinds := make([]string, 0, len(providers))
	for kind := range providers {
		kinds = append(kinds, kind)
	}
	sort.Strings(kinds)
	for _, kind := range kinds {
		installed := providers[kind]
		q := quota{State: "unknown"}
		if installed && kind == "codex" {
			q = codexQuota()
		}
		rows = append(rows, entry{Kind: kind, Installed: installed, Quota: q})
	}
	return map[string]any{"agents": rows}, nil
}

func install(ctx *sdk.Ctx, args map[string]string) (any, error) {
	kind := strings.TrimSpace(args["kind"])
	pkg, ok := packages[kind]
	if !ok {
		return nil, fmt.Errorf("unsupported agent: %s", kind)
	}
	argv := []string{"npm", "install", "-g", pkg}
	if kind == "pi" {
		argv = []string{"npm", "install", "-g", "--ignore-scripts", pkg}
	}
	result, err := ctx.CommandExec(argv, 300)
	if err != nil {
		return nil, err
	}
	if result.Exit != 0 {
		return nil, fmt.Errorf("installation failed (exit %d): %s", result.Exit, result.Output)
	}
	return map[string]any{"kind": kind, "installed": true}, nil
}

// Codex writes rate-limit snapshots into local session events. A stale snapshot is not a live quota.
func codexQuota() quota {
	unknown := quota{State: "unknown"}
	home, err := os.UserHomeDir()
	if err != nil {
		return unknown
	}
	root := filepath.Join(home, ".codex", "sessions")
	if custom := os.Getenv("CODEX_HOME"); custom != "" {
		root = filepath.Join(custom, "sessions")
	}
	type candidate struct {
		path string
		mod  time.Time
	}
	var files []candidate
	_ = filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(path, ".jsonl") {
			return nil
		}
		info, err := d.Info()
		if err == nil && time.Since(info.ModTime()) <= 24*time.Hour {
			files = append(files, candidate{path, info.ModTime()})
		}
		return nil
	})
	sort.Slice(files, func(i, j int) bool { return files[i].mod.After(files[j].mod) })
	for i, file := range files {
		if i == 8 {
			break
		}
		if q := quotaFromFile(file.path); q.State == "available" {
			return q
		}
	}
	return unknown
}

func quotaFromFile(path string) quota {
	unknown := quota{State: "unknown"}
	f, err := os.Open(path)
	if err != nil {
		return unknown
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return unknown
	}
	reader := bufio.NewReader(f)
	if info.Size() > 2<<20 {
		_, _ = f.Seek(info.Size()-(2<<20), 0)
		_, _ = reader.ReadString('\n')
	}
	s := bufio.NewScanner(reader)
	s.Buffer(make([]byte, 4096), 2<<20)
	var found quota = unknown
	for s.Scan() {
		if !strings.Contains(s.Text(), `"rate_limits"`) {
			continue
		}
		var event struct {
			Timestamp string `json:"timestamp"`
			Payload   struct {
				RateLimits struct {
					Primary *struct {
						Used   float64 `json:"used_percent"`
						Window int     `json:"window_minutes"`
						Reset  int64   `json:"resets_at"`
					} `json:"primary"`
					Secondary *struct {
						Used   float64 `json:"used_percent"`
						Window int     `json:"window_minutes"`
						Reset  int64   `json:"resets_at"`
					} `json:"secondary"`
				} `json:"rate_limits"`
			} `json:"payload"`
		}
		if json.Unmarshal(s.Bytes(), &event) != nil {
			continue
		}
		observed, err := time.Parse(time.RFC3339Nano, event.Timestamp)
		if err != nil || time.Since(observed) > 24*time.Hour {
			continue
		}
		var windows []quotaWindow
		for _, p := range []*struct {
			Used   float64 `json:"used_percent"`
			Window int     `json:"window_minutes"`
			Reset  int64   `json:"resets_at"`
		}{event.Payload.RateLimits.Primary, event.Payload.RateLimits.Secondary} {
			if p == nil || (p.Reset != 0 && p.Reset < time.Now().Unix()) {
				continue
			}
			windows = append(windows, quotaWindow{Remaining: max(0, 100-p.Used), WindowMin: p.Window, ResetsAt: p.Reset})
		}
		if len(windows) == 0 {
			continue
		}
		remaining := windows[0].Remaining
		found = quota{Remaining: &remaining, WindowMin: windows[0].WindowMin, ResetsAt: windows[0].ResetsAt, ObservedAt: event.Timestamp, Source: "Codex local session", State: "available", Windows: windows}
	}
	return found
}
