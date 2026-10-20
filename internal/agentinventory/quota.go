package agentinventory

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type AgentQuota struct {
	Reason     string        `json:"reason,omitempty"`
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

// Codex writes rate-limit snapshots into local session events. A stale snapshot is not a live quota.
func codexQuota() AgentQuota {
	unknown := AgentQuota{State: "unknown"}
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

func quotaFromFile(path string) AgentQuota {
	unknown := AgentQuota{State: "unknown"}
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
	var found AgentQuota = unknown
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
		found = AgentQuota{Remaining: &remaining, WindowMin: windows[0].WindowMin, ResetsAt: windows[0].ResetsAt, ObservedAt: event.Timestamp, Source: "Codex local session", State: "available", Windows: windows}
	}
	return found
}
