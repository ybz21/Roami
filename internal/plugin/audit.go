package plugin

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// AuditEntry is one JSONL record; every roam/* host-API call gets one
// (决策 allowed/denied 都记,见 docs/design/plugin/07-security.md §4).
type AuditEntry struct {
	Time     string `json:"time"`
	Plugin   string `json:"plugin"`
	Version  string `json:"version"`
	Actor    string `json:"actor"` // <kind>:<id>,如 cli:user / plugin:roam.monitor
	Action   string `json:"action"`
	Target   string `json:"target,omitempty"`
	Decision string `json:"decision"` // allowed | denied
	Result   string `json:"result,omitempty"`
}

// Audit appends an entry to today's audit log; failures are silent (审计不
// 阻断业务,但 stderr 可见)。
func (e Env) Audit(entry AuditEntry) {
	entry.Time = e.RT.Now().Format(time.RFC3339)
	day := e.RT.Now().Format("2006-01-02")
	path := filepath.Join(e.AuditDir(), day+".jsonl")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	b, err := json.Marshal(entry)
	if err != nil {
		return
	}
	f.Write(append(b, '\n'))
}

// AuditTail returns the last n lines of recent audit logs (newest first),
// optionally filtered by plugin id.
func (e Env) AuditTail(pluginID string, n int) ([]AuditEntry, error) {
	files, err := filepath.Glob(filepath.Join(e.AuditDir(), "*.jsonl"))
	if err != nil {
		return nil, err
	}
	var out []AuditEntry
	// newest files last in glob order (dates sort lexically)
	for i := len(files) - 1; i >= 0 && len(out) < n; i-- {
		b, err := os.ReadFile(files[i])
		if err != nil {
			continue
		}
		lines := splitLinesReverse(string(b))
		for _, line := range lines {
			var entry AuditEntry
			if json.Unmarshal([]byte(line), &entry) != nil {
				continue
			}
			if pluginID != "" && entry.Plugin != pluginID {
				continue
			}
			out = append(out, entry)
			if len(out) >= n {
				break
			}
		}
	}
	return out, nil
}

func splitLinesReverse(s string) []string {
	var lines []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			if i > start {
				lines = append(lines, s[start:i])
			}
			start = i + 1
		}
	}
	if start < len(s) {
		lines = append(lines, s[start:])
	}
	for i, j := 0, len(lines)-1; i < j; i, j = i+1, j-1 {
		lines[i], lines[j] = lines[j], lines[i]
	}
	return lines
}
