package api

import (
	"bufio"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

func piSessionsRoot() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".pi", "agent", "sessions")
}

type piEntry struct {
	Type      string          `json:"type"`
	ID        string          `json:"id"`
	ParentID  string          `json:"parentId"`
	Timestamp string          `json:"timestamp"`
	Cwd       string          `json:"cwd"`
	ModelID   string          `json:"modelId"`
	Message   json.RawMessage `json:"message"`
}

func piHeader(file string) (piEntry, bool) {
	f, err := os.Open(file)
	if err != nil {
		return piEntry{}, false
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 4096), 1<<20)
	var entry piEntry
	ok := scanner.Scan() && json.Unmarshal(scanner.Bytes(), &entry) == nil && entry.Type == "session" && entry.ID != ""
	return entry, ok
}

func pickPiTranscript(root, dir string, argv []string, start time.Time) string {
	id, file := "", ""
	for i, arg := range argv {
		if arg == "--no-session" {
			return ""
		}
		if (arg == "--session-id" || arg == "--session") && i+1 < len(argv) {
			id = argv[i+1]
			if strings.HasSuffix(id, ".jsonl") {
				file = id
				if !filepath.IsAbs(file) {
					file = filepath.Join(dir, file)
				}
			}
		}
	}
	if file != "" {
		actual, err := filepath.EvalSymlinks(file)
		if err != nil || !transcriptFileWithin(root, actual) {
			return ""
		}
		if _, ok := piHeader(actual); ok {
			return actual
		}
		return ""
	}
	// Partial IDs and ambiguous same-directory files must never select a different instance.
	if id != "" {
		file = providerTranscriptFile(root, "_"+id+".jsonl", false)
		header, ok := piHeader(file)
		if ok && header.ID == id {
			return file
		}
		return ""
	}
	found := ""
	project := "--" + strings.NewReplacer("/", "-", "\\", "-", ":", "-").Replace(strings.TrimLeft(dir, "/\\")) + "--"
	entries, _ := os.ReadDir(filepath.Join(root, project))
	for _, entry := range entries {
		if !entry.Type().IsRegular() || !strings.HasSuffix(entry.Name(), ".jsonl") {
			continue
		}
		candidate := filepath.Join(root, project, entry.Name())
		header, ok := piHeader(candidate)
		created, err := time.Parse(time.RFC3339Nano, header.Timestamp)
		if !ok || header.Cwd != dir || err != nil || created.Before(start.Add(-3*time.Second)) {
			continue
		}
		if found != "" {
			return ""
		}
		found = candidate
	}
	return found
}

func parsePiMessage(entry piEntry) (cMsg, string) {
	var src struct {
		Role       string          `json:"role"`
		Content    json.RawMessage `json:"content"`
		ToolCallID string          `json:"toolCallId"`
		IsError    bool            `json:"isError"`
		Model      string          `json:"model"`
	}
	if entry.Type != "message" || json.Unmarshal(entry.Message, &src) != nil {
		return cMsg{}, ""
	}
	m := cMsg{ID: entry.ID, Role: src.Role, Ts: entry.Timestamp, Blocks: []cBlock{}}
	if src.Role != "user" && src.Role != "assistant" && src.Role != "toolResult" {
		return cMsg{}, ""
	}
	var text string
	if json.Unmarshal(src.Content, &text) == nil {
		m.Blocks = append(m.Blocks, cBlock{Kind: "text", Text: clip(text)})
	} else {
		var parts []struct {
			Type      string          `json:"type"`
			Text      string          `json:"text"`
			Thinking  string          `json:"thinking"`
			ID        string          `json:"id"`
			Name      string          `json:"name"`
			Arguments json.RawMessage `json:"arguments"`
		}
		_ = json.Unmarshal(src.Content, &parts)
		for _, part := range parts {
			switch part.Type {
			case "text":
				m.Blocks = append(m.Blocks, cBlock{Kind: "text", Text: clip(part.Text)})
			case "thinking":
				m.Blocks = append(m.Blocks, cBlock{Kind: "thinking", Text: clip(part.Thinking)})
			case "toolCall":
				m.Blocks = append(m.Blocks, cBlock{Kind: "tool_use", ID: part.ID, Name: part.Name, Input: clip(string(part.Arguments))})
			}
		}
	}
	if src.Role == "toolResult" {
		m.Role = "tool"
		texts := make([]string, 0, len(m.Blocks))
		for _, block := range m.Blocks {
			texts = append(texts, block.Text)
		}
		m.Blocks = []cBlock{{Kind: "tool_result", ToolUseID: src.ToolCallID, Text: clip(strings.Join(texts, "\n")), IsError: src.IsError}}
	}
	return m, src.Model
}

// Pi appends a tree, so each changed window replaces the previous branch projection.
func piBranch(lines []transcriptLine, limit int) ([]cMsg, cStatus, bool) {
	entries := map[string]piEntry{}
	leaf := ""
	status := cStatus{}
	for _, line := range lines {
		var entry piEntry
		if json.Unmarshal(line.Text, &entry) != nil || entry.Type == "session" || entry.ID == "" {
			continue
		}
		entries[entry.ID], leaf = entry, entry.ID
	}
	path := []piEntry{}
	seen := map[string]bool{}
	for leaf != "" && !seen[leaf] {
		entry, ok := entries[leaf]
		if !ok {
			break
		}
		seen[leaf] = true
		path = append(path, entry)
		leaf = entry.ParentID
	}
	window := newTranscriptWindow(limit)
	for i := len(path) - 1; i >= 0; i-- {
		entry := path[i]
		if entry.Type == "model_change" {
			status.Model = entry.ModelID
		}
		if message, model := parsePiMessage(entry); len(message.Blocks) > 0 {
			window.add(message)
			if model != "" {
				status.Model = model
			}
		}
	}
	messages, truncated := window.out()
	return messages, status, truncated || leaf != ""
}

func (a *API) PiTranscript(c *gin.Context) {
	name := a.sessionTarget(c)
	file, managed := managedTranscript(name, "pi")
	if !managed {
		if dir, pid := paneToolProc(name, cmdlineHasPi); dir != "" {
			file = pickPiTranscript(piSessionsRoot(), dir, processArgv(pid), processStart(pid))
		}
	}
	empty := gin.H{"messages": []cMsg{}, "nextOffset": 0, "file": "", "replace": true}
	if file == "" {
		c.JSON(http.StatusOK, gin.H{"data": empty})
		return
	}
	header, valid := piHeader(file)
	if !valid {
		c.JSON(http.StatusOK, gin.H{"data": empty})
		return
	}
	f, err := os.Open(file)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"data": empty})
		return
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"data": empty})
		return
	}
	offset, _ := strconv.ParseInt(c.Query("offset"), 10, 64)
	if offset > 0 && offset == info.Size() && c.Query("file") == file {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"messages": []cMsg{}, "nextOffset": offset, "file": file}})
		return
	}
	limit := tailLimit(c, 0)
	if limit == 0 {
		limit = 200
	}
	lines, _, _, err := readTail(f, limit*10)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "PI_TRANSCRIPT_READ"}})
		return
	}
	messages, status, truncated := piBranch(lines, limit)
	status.Cwd = header.Cwd
	pending := false
	if len(messages) > 0 {
		last := messages[len(messages)-1]
		pending = last.Role == "user" || last.Role == "tool" || last.Role == "assistant" && last.Blocks[len(last.Blocks)-1].Kind == "tool_use"
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"messages": messages, "nextOffset": lastComplete(lines, 0), "file": file, "status": status, "replace": true, "truncated": truncated, "pending": pending}})
}
