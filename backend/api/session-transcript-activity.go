package api

import (
	"database/sql"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type activityTranscriptKey struct {
	session, identity, pane string
	proc                    agentProc
}

type activityTranscript struct {
	file      string
	unique    bool
	recheckAt time.Time
	info      os.FileInfo
	at        int64
	offset    int64
}

func usesTranscriptActivity(kind string) bool { return kind == "codex" || kind == "claude" }

func (previous activityTranscripts) sample(panes []sessionPane, now time.Time) activityTranscripts {
	next := make(activityTranscripts)
	codexByDir := make(map[string]map[int]bool)
	for _, pane := range panes {
		if p := pane.agent; p.Kind == "codex" {
			if codexByDir[p.Dir] == nil {
				codexByDir[p.Dir] = make(map[int]bool)
			}
			codexByDir[p.Dir][p.Pid] = true
		}
	}
	for i := range panes {
		pane := &panes[i]
		if !usesTranscriptActivity(pane.agent.Kind) {
			continue
		}
		key := activityTranscriptKey{pane.session, pane.identity, pane.id, pane.agent}
		record := previous[key]
		unique := len(codexByDir[pane.agent.Dir]) == 1
		if unique != record.unique || !now.Before(record.recheckAt) {
			file := activityTranscriptFile(pane.session, pane.agent, unique)
			if record.file != file {
				record = activityTranscript{file: file}
			}
			record.unique, record.recheckAt = unique, now.Add(time.Minute)
		}
		record.read(pane.agent.Kind)
		pane.confirmedAt = record.at
		next[key] = record
	}
	return next
}

type activityTranscripts map[activityTranscriptKey]activityTranscript

func (record *activityTranscript) read(kind string) {
	if record.file == "" {
		return
	}
	info, err := os.Stat(record.file)
	if err != nil || !info.Mode().IsRegular() {
		return
	}
	old := record.info
	sameFile := old != nil && os.SameFile(old, info)
	if sameFile && info.Size() == old.Size() && info.ModTime().Equal(old.ModTime()) {
		return
	}
	file, err := os.Open(record.file)
	if err != nil {
		return
	}
	defer file.Close()
	at, offset := record.at, record.offset
	if !sameFile || info.Size() <= old.Size() {
		at, offset = 0, 0
	}
	// Continue before the first complete row on each page, including on cold start.
	const pageLines = 128
	now := time.Now()
	end := info.Size()
	nextOffset := offset
	for end > offset {
		lines, _, _, err := readTailBefore(file, pageLines, end)
		if err != nil {
			return
		}
		if len(lines) == 0 {
			break
		}
		nextOffset = max(nextOffset, lastComplete(lines, offset))
		for _, line := range lines {
			if line.At >= offset {
				at = max(at, transcriptMessageTime(kind, string(line.Text), now))
			}
		}
		if offset == 0 && at > 0 {
			break
		}
		end = lines[0].At
	}
	record.info, record.at, record.offset = info, at, nextOffset
}

func transcriptMessageTime(kind, text string, now time.Time) int64 {
	var message *cMsg
	switch kind {
	case "codex":
		message = parseCodexLine(text)
	case "claude":
		message = parseLine(text)
	}
	if message == nil || (message.Role != "user" && message.Role != "assistant") {
		return 0
	}
	at, err := time.Parse(time.RFC3339Nano, message.Ts)
	if err != nil || at.IsZero() || at.After(now) {
		return 0
	}
	for _, block := range message.Blocks {
		if block.Kind == "text" && strings.TrimSpace(block.Text) != "" || block.Kind == "image" {
			return at.Unix()
		}
	}
	return 0
}

func activityTranscriptFile(name string, p agentProc, uniqueCodexDir bool) string {
	file, managed := managedTranscript(name, p.Kind)
	if file != "" {
		return file
	}
	return nativeActivityTranscriptFile(p, uniqueCodexDir && !managed)
}

func nativeActivityTranscriptFile(p agentProc, uniqueCodexDir bool) string {
	argv := processArgv(p.Pid)
	if p.Kind == "codex" {
		id := codexResumeID(argv)
		if id != "" {
			if file := codexActivityFile(id, "", time.Time{}); file != "" {
				return file
			}
			return providerTranscriptFile(codexSessionsRoot(), "-"+id+".jsonl", false)
		}
		if uniqueCodexDir && p.Dir != "" {
			if started := processStart(p.Pid); !started.IsZero() {
				return codexActivityFile("", p.Dir, started)
			}
		}
		return ""
	}
	id := claudeProcessSession(p.Pid)
	if id == "" {
		id = argvSessionID(argv)
	}
	if id != "" {
		return findTranscript(claudeTranscriptRoot(), projectDirFor(p.Dir), id)
	}
	return ""
}

func claudeProcessSession(pid int) string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	raw, err := os.ReadFile(filepath.Join(home, ".claude", "sessions", strconv.Itoa(pid)+".json"))
	if err != nil {
		return ""
	}
	var record struct {
		PID       int    `json:"pid"`
		ProcStart string `json:"procStart"`
		SessionID string `json:"sessionId"`
	}
	if json.Unmarshal(raw, &record) != nil || record.PID != pid || record.ProcStart == "" || !uuidLike.MatchString(record.SessionID) {
		return ""
	}
	stat, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
	end := strings.LastIndexByte(string(stat), ')')
	if err != nil || end == -1 {
		return ""
	}
	fields := strings.Fields(string(stat[end+1:]))
	if len(fields) < 20 || fields[19] != record.ProcStart {
		return ""
	}
	return record.SessionID
}

func codexActivityFile(id, dir string, started time.Time) string {
	db := openCodexState()
	if db == nil {
		return ""
	}
	defer db.Close()
	query := "SELECT rollout_path FROM threads WHERE id=?"
	args := []any{id}
	if id == "" {
		query = "SELECT rollout_path FROM threads WHERE cwd=? AND archived=0 AND updated_at_ms>=? LIMIT 2"
		args = []any{dir, started.UnixMilli()}
	}
	return uniqueCodexActivityFile(db, codexSessionsRoot(), query, args...)
}

func uniqueCodexActivityFile(db *sql.DB, root, query string, args ...any) string {
	rows, err := db.Query(query, args...)
	if err != nil {
		return ""
	}
	defer rows.Close()
	var path string
	if !rows.Next() || rows.Scan(&path) != nil || rows.Next() || rows.Err() != nil || !transcriptFileWithin(root, path) {
		return ""
	}
	return path
}
