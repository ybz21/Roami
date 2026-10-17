package swarm

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Post is one plaza message.
type Post struct {
	ID     int    `json:"id"`
	TS     string `json:"ts"`
	Author string `json:"author"`
	Kind   string `json:"kind"`
	Re     any    `json:"re"`
	Text   string `json:"text"`
}

// AddPost inserts a plaza message and returns its id (mirrors _plaza_say insert).
func (s *Store) AddPost(swarm, author, kind string, re *int, text string) (int, error) {
	db, err := s.openSwarmDB(swarm)
	if err != nil {
		return 0, err
	}
	defer db.Close()
	var res interface {
		LastInsertId() (int64, error)
	}
	var reVal any
	if re != nil {
		reVal = *re
	}
	r, err := db.Exec(`INSERT INTO posts(ts,author,kind,re,text)
		VALUES(datetime('now','localtime'),?,?,?,?)`, author, kind, reVal, text)
	if err != nil {
		return 0, err
	}
	res = r
	id, err := res.LastInsertId()
	return int(id), err
}

// Feed returns recent posts (most recent n, ascending) with optional filters.
func (s *Store) Feed(swarm string, n int, from, kind string, since int) ([]Post, error) {
	db, err := s.openSwarmDB(swarm)
	if err != nil {
		return nil, err
	}
	defer db.Close()
	where := "1=1"
	var qargs []any
	if from != "" {
		where += " AND author=?"
		qargs = append(qargs, from)
	}
	if kind != "" {
		where += " AND kind=?"
		qargs = append(qargs, kind)
	}
	if since > 0 {
		where += " AND id>?"
		qargs = append(qargs, since)
	}
	q := fmt.Sprintf(`SELECT id,ts,author,kind,re,text FROM
		(SELECT * FROM posts WHERE %s ORDER BY id DESC LIMIT %d) ORDER BY id`, where, n)
	rows, err := db.Query(q, qargs...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Post
	for rows.Next() {
		var p Post
		var re any
		if err := rows.Scan(&p.ID, &p.TS, &p.Author, &p.Kind, &re, &p.Text); err != nil {
			return nil, err
		}
		p.Re = normalizeRe(re)
		out = append(out, p)
	}
	return out, rows.Err()
}

// PostsSince returns posts with id greater than after (ascending) — for watch.
func (s *Store) PostsSince(swarm string, after int) ([]Post, error) {
	db, err := s.openSwarmDB(swarm)
	if err != nil {
		return nil, err
	}
	defer db.Close()
	rows, err := db.Query(`SELECT id,ts,author,kind,re,text FROM posts WHERE id>? ORDER BY id`, after)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Post
	for rows.Next() {
		var p Post
		var re any
		if err := rows.Scan(&p.ID, &p.TS, &p.Author, &p.Kind, &re, &p.Text); err != nil {
			return nil, err
		}
		p.Re = normalizeRe(re)
		out = append(out, p)
	}
	return out, rows.Err()
}

// MaxPostID returns the highest post id (0 if none).
func (s *Store) MaxPostID(swarm string) int {
	db, err := s.openSwarmDB(swarm)
	if err != nil {
		return 0
	}
	defer db.Close()
	var n int
	_ = db.QueryRow(`SELECT IFNULL(MAX(id),0) FROM posts`).Scan(&n)
	return n
}

func normalizeRe(re any) any {
	switch t := re.(type) {
	case nil:
		return nil
	case int64:
		return int(t)
	case int:
		return t
	default:
		return t
	}
}

// ActiveMembers lists launched (non-pending) member names.
func (s *Store) ActiveMembers(swarm string) []string {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return nil
	}
	defer db.Close()
	rows, err := db.Query(`SELECT name FROM swarm_members WHERE swarm_id=? AND IFNULL(pending,0)=0`, sid)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var n string
		if rows.Scan(&n) == nil {
			out = append(out, n)
		}
	}
	return out
}

// TouchBusy marks members busy (mirrors _swarm_member_touch_busy). target may be
// "leader"/"all"/a member name.
func (s *Store) TouchBusy(swarm, target string) {
	id := s.ResolveID(swarm)
	if id == "" {
		return
	}
	var targets []string
	switch target {
	case "leader", "master", "lead":
		targets = s.roleMembers(swarm, "leader", "master")
	case "all":
		targets = s.ActiveMembers(swarm)
	default:
		targets = []string{target}
	}
	dir := filepath.Join(s.swarmHome(id), "busy")
	_ = os.MkdirAll(dir, 0o755)
	now := fmt.Sprintf("%d", s.opt.Now().Unix())
	for _, m := range targets {
		if m == "" {
			continue
		}
		_ = os.WriteFile(filepath.Join(dir, m+".busy"), []byte(now+"\n"), 0o644)
	}
}

// LeaderMembers lists launched leader/master members.
func (s *Store) LeaderMembers(swarm string) []string {
	return s.roleMembers(swarm, "leader", "master")
}

func (s *Store) roleMembers(swarm string, roles ...string) []string {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return nil
	}
	defer db.Close()
	ph := strings.TrimSuffix(strings.Repeat("?,", len(roles)), ",")
	args := make([]any, 0, len(roles)+1)
	args = append(args, sid)
	for _, r := range roles {
		args = append(args, r)
	}
	rows, err := db.Query(`SELECT name FROM swarm_members WHERE swarm_id=? AND role IN (`+ph+`) AND IFNULL(pending,0)=0`, args...)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var n string
		if rows.Scan(&n) == nil {
			out = append(out, n)
		}
	}
	return out
}

// ── listener cursor (per-swarm, per-key files) ──

func (s *Store) listenerDir(swarm string) (string, bool) {
	id := s.ResolveID(swarm)
	if id == "" {
		return "", false
	}
	return filepath.Join(s.swarmHome(id), "listeners"), true
}

func listenerKey(key string) string {
	if key == "master" || key == "lead" {
		key = "leader"
	}
	var b strings.Builder
	for _, r := range key {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' || r == '.' || r == '-' {
			b.WriteRune(r)
		} else {
			b.WriteRune('_')
		}
	}
	if b.Len() == 0 {
		return "leader"
	}
	return b.String()
}

func (s *Store) ListenerLastGet(swarm, key string) int {
	dir, ok := s.listenerDir(swarm)
	if !ok {
		return 0
	}
	b, err := os.ReadFile(filepath.Join(dir, listenerKey(key)+".last_post"))
	if err != nil {
		return 0
	}
	var n int
	_, _ = fmt.Sscanf(strings.TrimSpace(string(b)), "%d", &n)
	return n
}

func (s *Store) ListenerLastSet(swarm, key string, val int) error {
	dir, ok := s.listenerDir(swarm)
	if !ok {
		return fmt.Errorf("swarm not found: %s", swarm)
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, listenerKey(key)+".last_post"), []byte(fmt.Sprintf("%d\n", val)), 0o644)
}
