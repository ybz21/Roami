package api

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"time"

	"ttmux-web/worktree"
)

// GitFootprintStore owns a separate archive; meta.db schema remains CLI-owned.
type GitFootprintStore struct {
	db  *sql.DB
	err error
}

func NewGitFootprintStore(dataDir string) *GitFootprintStore {
	s := &GitFootprintStore{}
	if s.err = os.MkdirAll(dataDir, 0o755); s.err != nil {
		return s
	}
	s.db, s.err = sql.Open("sqlite", "file:"+filepath.Join(dataDir, "ai-footprints.db")+"?_pragma=busy_timeout(10000)")
	if s.err != nil {
		return s
	}
	s.db.SetMaxOpenConns(1)
	_, s.err = s.db.Exec(`CREATE TABLE IF NOT EXISTS git_commits (oid TEXT PRIMARY KEY, at INTEGER NOT NULL)`)
	return s
}

func (s *GitFootprintStore) Import(ctx context.Context, commits []worktree.ActivityCommit) error {
	if s.err != nil {
		return s.err
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	stmt, err := tx.PrepareContext(ctx, `INSERT INTO git_commits (oid, at) VALUES (?, ?) ON CONFLICT(oid) DO NOTHING`)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, commit := range commits {
		if _, err := stmt.ExecContext(ctx, commit.OID, commit.At); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *GitFootprintStore) Recent(ctx context.Context) ([]worktree.ActivityCommit, error) {
	if s.err != nil {
		return nil, s.err
	}
	rows, err := s.db.QueryContext(ctx, `SELECT oid, at FROM git_commits WHERE at >= ? ORDER BY at, oid`, time.Now().AddDate(0, 0, -370).Unix())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	commits := []worktree.ActivityCommit{}
	for rows.Next() {
		var commit worktree.ActivityCommit
		if err := rows.Scan(&commit.OID, &commit.At); err != nil {
			return nil, err
		}
		commits = append(commits, commit)
	}
	return commits, rows.Err()
}
