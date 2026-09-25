package api

// 收件箱：会话级事件（等你 / 做完 / 出错）落在台账的 plugin_notifications 表里（和插件通知同一张表，
// source=roam.web），已读状态记在 dataDir/inbox-read.json。手机版的首页就是它（24 稿 §5）。
//
// 表没有 session 列：会话名放在 dedupe 里，格式 "<type>|<session>|<unix>"——dedupe 本来就是自由文本，
// 插件那边的 5 分钟去重按整串比，不会和这里撞。

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

const inboxSource = "roam.web"

type InboxStore struct {
	file   string
	mu     sync.Mutex
	readUp int64          // 「全部已读」水位：id <= readUp 都算已读
	read   map[int64]bool // 水位之上单独标过已读的
	db     func() *sql.DB // 台账；nil 或降级时收件箱为空
}

func NewInboxStore(dataDir string, db func() *sql.DB) *InboxStore {
	s := &InboxStore{file: filepath.Join(dataDir, "inbox-read.json"), read: map[int64]bool{}, db: db}
	var st struct {
		ReadUp int64   `json:"readUp"`
		Read   []int64 `json:"read"`
	}
	if b, err := os.ReadFile(s.file); err == nil && json.Unmarshal(b, &st) == nil {
		s.readUp = st.ReadUp
		for _, id := range st.Read {
			s.read[id] = true
		}
	}
	return s
}

func (s *InboxStore) save() {
	ids := make([]int64, 0, len(s.read))
	for id := range s.read {
		if id > s.readUp {
			ids = append(ids, id)
		}
	}
	b, _ := json.Marshal(struct {
		ReadUp int64   `json:"readUp"`
		Read   []int64 `json:"read"`
	}{s.readUp, ids})
	_ = os.WriteFile(s.file, b, 0o600)
}

type inboxItem struct {
	ID      int64  `json:"id"`
	Type    string `json:"type"`
	Session string `json:"session"`
	Label   string `json:"label"`
	Body    string `json:"body"`
	At      int64  `json:"at"`
	Read    bool   `json:"read"`
}

// Publish 落一条并返回 id；db 不可用返回 0（推送照发，只是收件箱里没有）
func (s *InboxStore) Publish(typ, session, label, body string) int64 {
	db := s.db()
	if db == nil {
		return 0
	}
	sev := "info"
	switch typ {
	case "session.waiting":
		sev = "warn"
	case "session.error":
		sev = "error"
	}
	now := time.Now()
	res, err := db.Exec(`INSERT INTO plugin_notifications (type, severity, title, body, source, dedupe, created) VALUES (?,?,?,?,?,?,?)`,
		typ, sev, label, body, inboxSource, fmt.Sprintf("%s|%s|%d", typ, session, now.Unix()), now.UTC().Format(time.RFC3339))
	if err != nil {
		return 0
	}
	id, _ := res.LastInsertId()
	return id
}

func (s *InboxStore) list(limit int) []inboxItem {
	db := s.db()
	if db == nil {
		return []inboxItem{}
	}
	rows, err := db.Query(`SELECT id, type, title, body, dedupe, created FROM plugin_notifications WHERE source=? ORDER BY id DESC LIMIT ?`, inboxSource, limit)
	if err != nil {
		return []inboxItem{}
	}
	defer rows.Close()
	s.mu.Lock()
	defer s.mu.Unlock()
	out := []inboxItem{}
	for rows.Next() {
		var it inboxItem
		var dedupe, created string
		if rows.Scan(&it.ID, &it.Type, &it.Label, &it.Body, &dedupe, &created) != nil {
			continue
		}
		parts := strings.SplitN(dedupe, "|", 3)
		if len(parts) == 3 {
			it.Session = parts[1]
			it.At, _ = strconv.ParseInt(parts[2], 10, 64)
		}
		if it.At == 0 {
			if t, e := time.Parse(time.RFC3339, created); e == nil {
				it.At = t.Unix()
			}
		}
		it.Read = it.ID <= s.readUp || s.read[it.ID]
		out = append(out, it)
	}
	return out
}

// Unread 需要你且未读的条数 = 角标
func (s *InboxStore) Unread() int {
	n := 0
	for _, it := range s.list(200) {
		if !it.Read && it.Type == "session.waiting" {
			n++
		}
	}
	return n
}

// GET /inbox?limit=
func (a *API) InboxList(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "100"))
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	items := a.Inbox.list(limit)
	badge := 0
	for _, it := range items {
		if !it.Read && it.Type == "session.waiting" {
			badge++
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"items": items, "badge": badge}})
}

// POST /inbox/read {ids:[…]} 或 {all:true}
func (a *API) InboxRead(c *gin.Context) {
	var b struct {
		IDs []int64 `json:"ids"`
		All bool    `json:"all"`
	}
	_ = c.ShouldBindJSON(&b)
	a.Inbox.mu.Lock()
	if b.All {
		if items := a.Inbox.listUnlocked(1); len(items) > 0 {
			a.Inbox.readUp = items[0].ID
		}
		a.Inbox.read = map[int64]bool{}
	}
	for _, id := range b.IDs {
		a.Inbox.read[id] = true
	}
	a.Inbox.save()
	a.Inbox.mu.Unlock()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"badge": a.Inbox.Unread()}})
}

// listUnlocked：调用方已持锁时用，只取最新 n 条的 id
func (s *InboxStore) listUnlocked(limit int) []inboxItem {
	db := s.db()
	if db == nil {
		return nil
	}
	rows, err := db.Query(`SELECT id FROM plugin_notifications WHERE source=? ORDER BY id DESC LIMIT ?`, inboxSource, limit)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []inboxItem
	for rows.Next() {
		var it inboxItem
		if rows.Scan(&it.ID) == nil {
			out = append(out, it)
		}
	}
	return out
}
