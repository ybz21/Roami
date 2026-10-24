package api

import (
	"database/sql"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// 恢复旧对话后 Codex 会更新 state 中的 cwd，但 rollout 首行仍是创建时的目录。
func codexStateRollout(cwd string, started time.Time) string {
	if cwd == "" || started.IsZero() {
		return ""
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	paths, _ := filepath.Glob(filepath.Join(home, ".codex", "state_*.sqlite"))
	sort.Slice(paths, func(i, j int) bool {
		return codexStateVersion(paths[i]) > codexStateVersion(paths[j])
	})
	if len(paths) == 0 {
		return ""
	}
	db, err := sql.Open("sqlite", "file:"+paths[0]+"?mode=ro")
	if err != nil {
		return ""
	}
	defer db.Close()
	return pickCodexStateRollout(db, cwd, started, codexSessionsRoot())
}

func codexStateVersion(path string) int {
	name := filepath.Base(path)
	n, _ := strconv.Atoi(strings.TrimSuffix(strings.TrimPrefix(name, "state_"), ".sqlite"))
	return n
}

func pickCodexStateRollout(db *sql.DB, cwd string, started time.Time, root string) string {
	rows, err := db.Query(`SELECT rollout_path FROM threads
		WHERE cwd=? AND archived=0 AND updated_at_ms>=?
		ORDER BY updated_at_ms DESC LIMIT 2`, cwd, started.Add(-2*time.Minute).UnixMilli())
	if err != nil {
		return ""
	}
	defer rows.Close()
	var path string
	if !rows.Next() || rows.Scan(&path) != nil || rows.Next() {
		return ""
	}
	path = filepath.Clean(path)
	if !strings.HasPrefix(path, filepath.Clean(root)+string(filepath.Separator)) {
		return ""
	}
	if _, err := os.Stat(path); err != nil {
		return ""
	}
	return path
}
