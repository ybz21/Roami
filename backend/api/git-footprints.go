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
	_, s.err = s.db.Exec(`CREATE TABLE IF NOT EXISTS git_commits (oid TEXT PRIMARY KEY, at INTEGER NOT NULL, repo TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '')`)
	if s.err == nil {
		s.err = s.migrateDetails()
	}
	return s
}

func (s *GitFootprintStore) migrateDetails() error {
	rows, err := s.db.Query(`PRAGMA table_info(git_commits)`)
	if err != nil {
		return err
	}
	columns := map[string]bool{}
	for rows.Next() {
		var index, notNull, primary int
		var name, typ string
		var def any
		if err := rows.Scan(&index, &name, &typ, &notNull, &def, &primary); err != nil {
			rows.Close()
			return err
		}
		columns[name] = true
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, name := range []string{"repo", "subject"} {
		if !columns[name] {
			if _, err := s.db.Exec(`ALTER TABLE git_commits ADD COLUMN ` + name + ` TEXT NOT NULL DEFAULT ''`); err != nil {
				return err
			}
		}
	}
	_, err = s.db.Exec(`CREATE INDEX IF NOT EXISTS git_commits_at ON git_commits(at)`)
	return err
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
	stmt, err := tx.PrepareContext(ctx, `INSERT INTO git_commits (oid, at, repo, subject) VALUES (?, ?, ?, ?) ON CONFLICT(oid) DO UPDATE SET repo=excluded.repo, subject=excluded.subject WHERE git_commits.repo='' AND excluded.repo<>''`)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, commit := range commits {
		if _, err := stmt.ExecContext(ctx, commit.OID, commit.At, commit.Repo, commit.Subject); err != nil {
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

type GitDayFootprint struct {
	OID     string `json:"oid"`
	At      int64  `json:"at"`
	Repo    string `json:"repo"`
	Subject string `json:"subject"`
}

func (s *GitFootprintStore) Day(ctx context.Context, from, to int64) ([]GitDayFootprint, error) {
	if s.err != nil {
		return nil, s.err
	}
	rows, err := s.db.QueryContext(ctx, `SELECT oid, at, repo, subject FROM git_commits WHERE at >= ? AND at < ? ORDER BY at DESC, oid`, from, to)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	commits := []GitDayFootprint{}
	for rows.Next() {
		var commit GitDayFootprint
		if err := rows.Scan(&commit.OID, &commit.At, &commit.Repo, &commit.Subject); err != nil {
			return nil, err
		}
		commits = append(commits, commit)
	}
	return commits, rows.Err()
}
