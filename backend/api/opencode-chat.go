package api

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	_ "modernc.org/sqlite"
)

func openCodeDB() (*sql.DB, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}
	return sql.Open("sqlite", "file:"+filepath.Join(home, ".local/share/opencode/opencode.db")+"?mode=ro")
}

func openCodeResumeID(argv []string) string {
	for i, arg := range argv {
		if (arg == "--session" || arg == "-s") && i+1 < len(argv) && strings.HasPrefix(argv[i+1], "ses_") {
			return argv[i+1]
		}
	}
	return ""
}

func openCodeSessionDir(name, dir string) string {
	return paneWorktreeDir(dir, sessionCapture(name, 8))
}

func openCodeSession(db *sql.DB, dir string, pid int) string {
	if id := openCodeResumeID(processArgv(pid)); id != "" {
		var found string
		if db.QueryRow("SELECT id FROM session_v2 WHERE id=?", id).Scan(&found) == nil {
			return found
		}
	}
	start := processStart(pid).Add(-3 * time.Second).UnixMilli()
	var id string
	// A newly opened TUI must not inherit an older conversation in the same directory.
	_ = db.QueryRow(`SELECT id FROM session_v2 WHERE directory=? AND (time_created>=? OR time_viewed>=?)
		ORDER BY MAX(time_updated, COALESCE(time_viewed, 0)) DESC LIMIT 1`, dir, start, start).Scan(&id)
	return id
}

func (a *API) OpenCodeStatus(c *gin.Context) {
	name := a.sessionTarget(c)
	dir, pid := paneToolProc(name, cmdlineHasOpenCode)
	if dir == "" {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"running": false}})
		return
	}
	id := ""
	dir = openCodeSessionDir(name, dir)
	if db, err := openCodeDB(); err == nil {
		defer db.Close()
		id = openCodeSession(db, dir, pid)
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"running": true, "dir": dir, "file": id}})
}

type openCodePart struct {
	Type  string `json:"type"`
	Text  string `json:"text"`
	ID    string `json:"id"`
	Name  string `json:"name"`
	State struct {
		Status  string          `json:"status"`
		Input   json.RawMessage `json:"input"`
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
	} `json:"state"`
}

type openCodeMessage struct {
	Text    string         `json:"text"`
	Content []openCodePart `json:"content"`
	Time    struct {
		Created int64 `json:"created"`
	} `json:"time"`
	Model struct {
		ID string `json:"id"`
	} `json:"model"`
}

func parseOpenCodeMessage(id, kind, raw string) (cMsg, string) {
	var src openCodeMessage
	if json.Unmarshal([]byte(raw), &src) != nil {
		return cMsg{}, ""
	}
	role := kind
	if role != "user" && role != "assistant" {
		return cMsg{}, ""
	}
	m := cMsg{Role: role, ID: id, Ts: time.UnixMilli(src.Time.Created).UTC().Format(time.RFC3339Nano), Blocks: []cBlock{}}
	if role == "user" {
		if src.Text != "" {
			m.Blocks = append(m.Blocks, cBlock{Kind: "text", Text: clip(src.Text)})
		}
		return m, ""
	}
	for _, part := range src.Content {
		switch part.Type {
		case "text":
			if part.Text != "" {
				m.Blocks = append(m.Blocks, cBlock{Kind: "text", Text: clip(part.Text)})
			}
		case "reasoning":
			if part.Text != "" {
				m.Blocks = append(m.Blocks, cBlock{Kind: "thinking", Text: clip(part.Text)})
			}
		case "tool":
			m.Blocks = append(m.Blocks, cBlock{Kind: "tool_use", ID: part.ID, Name: part.Name, Input: clip(string(part.State.Input))})
			if part.State.Status == "completed" || part.State.Status == "error" {
				lines := make([]string, 0, len(part.State.Content))
				for _, item := range part.State.Content {
					if item.Text != "" {
						lines = append(lines, item.Text)
					}
				}
				m.Blocks = append(m.Blocks, cBlock{Kind: "tool_result", ToolUseID: part.ID, Text: clip(strings.Join(lines, "\n")), IsError: part.State.Status == "error"})
			}
		}
	}
	return m, src.Model.ID
}

func (a *API) OpenCodeTranscript(c *gin.Context) {
	name := a.sessionTarget(c)
	dir, pid := paneToolProc(name, cmdlineHasOpenCode)
	if dir == "" {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"messages": []cMsg{}, "nextOffset": 0, "file": ""}})
		return
	}
	db, err := openCodeDB()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "OPENCODE_DB"}})
		return
	}
	defer db.Close()
	dir = openCodeSessionDir(name, dir)
	id := openCodeSession(db, dir, pid)
	if id == "" {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"messages": []cMsg{}, "nextOffset": 0, "file": ""}})
		return
	}
	// The session id is resolved from this pane; never accept a client supplied database id.
	offset, _ := strconv.ParseInt(c.Query("offset"), 10, 64)
	tail := tailLimit(c, int(offset))
	if tail == 0 {
		tail = 200
	}
	var rows *sql.Rows
	if offset == 0 {
		rows, err = db.Query(`SELECT id,type,seq,data FROM (SELECT id,type,seq,data FROM session_message WHERE session_id=? AND type IN ('user','assistant') ORDER BY seq DESC LIMIT ?) ORDER BY seq`, id, tail)
	} else {
		// Include the last record because OpenCode updates a streaming assistant row in place.
		rows, err = db.Query(`SELECT id,type,seq,data FROM session_message WHERE session_id=? AND type IN ('user','assistant') AND seq>=? ORDER BY seq`, id, offset)
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "OPENCODE_DB"}})
		return
	}
	defer rows.Close()
	msgs := []cMsg{}
	next := offset
	status := gin.H{}
	for rows.Next() {
		var rowID, kind, data string
		var seq int64
		if rows.Scan(&rowID, &kind, &seq, &data) != nil {
			continue
		}
		if seq > next {
			next = seq
		}
		m, model := parseOpenCodeMessage(rowID, kind, data)
		if len(m.Blocks) > 0 {
			msgs = append(msgs, m)
		}
		if model != "" {
			status["model"] = model
		}
	}
	var earlier bool
	if offset == 0 && len(msgs) > 0 {
		var count int
		var firstSeq int64
		_ = db.QueryRow("SELECT seq FROM session_message WHERE id=?", msgs[0].ID).Scan(&firstSeq)
		_ = db.QueryRow("SELECT COUNT(*) FROM session_message WHERE session_id=? AND type IN ('user','assistant') AND seq<?", id, firstSeq).Scan(&count)
		earlier = count > 0
	}
	data := gin.H{"messages": msgs, "nextOffset": next, "file": id, "status": status}
	var lastType, lastData string
	if db.QueryRow("SELECT type,data FROM session_message WHERE session_id=? AND type IN ('user','assistant') ORDER BY seq DESC LIMIT 1", id).Scan(&lastType, &lastData) == nil {
		var last struct {
			Finish string `json:"finish"`
			Time   struct {
				Completed int64 `json:"completed"`
			} `json:"time"`
		}
		_ = json.Unmarshal([]byte(lastData), &last)
		data["pending"] = lastType == "user" || (lastType == "assistant" && last.Finish == "" && last.Time.Completed == 0)
	}
	if offset == 0 {
		data["truncated"] = earlier
	}
	c.JSON(http.StatusOK, gin.H{"data": data})
}
