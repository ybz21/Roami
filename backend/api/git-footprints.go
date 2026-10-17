package api

import (
	"context"
	"database/sql"
	"time"

	"github.com/ybz21/Roami/backend/worktree"
	metadb "github.com/ybz21/Roami/internal/storage"
)

// GitFootprintStore owns a separate archive; meta.db schema remains CLI-owned.
type GitFootprintStore struct {
	managed *metadb.DB
	db      *sql.DB
	err     error
}

func NewGitFootprintStore(dataDir string) *GitFootprintStore {
	s := &GitFootprintStore{}
	paths, e := metadb.ResolvePaths(dataDir, dataDir)
	if e != nil {
		s.err = e
		return s
	}
	if _, s.err = paths.Ensure(); s.err != nil {
		return s
	}
	s.managed, s.err = metadb.OpenManaged(paths, metadb.DatabaseDescriptor{ID: "git-archive", Kind: "archive", Path: paths.ArchivePath(), Owner: "git-archive"}, []metadb.Step{{Version: 1, Name: "git-archive", SQL: `CREATE TABLE IF NOT EXISTS git_commits (oid TEXT PRIMARY KEY, at INTEGER NOT NULL, repo TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '')`, Fn: func(tx *sql.Tx, _ metadb.Options) error {
		for _, name := range []string{"repo", "subject"} {
			if e := archiveColumn(tx, name); e != nil {
				return e
			}
		}
		_, e := tx.Exec(`CREATE INDEX IF NOT EXISTS git_commits_at ON git_commits(at)`)
		return e
	}}}, metadb.Options{})
	if s.err == nil {
		s.db = s.managed.DB
	}

	return s
}

func archiveColumn(tx *sql.Tx, name string) error {
	cols, e := metadb.Columns(tx, "git_commits")
	if e != nil {
		return e
	}
	if cols[name] {
		return nil
	}
	_, e = tx.Exec("ALTER TABLE git_commits ADD COLUMN " + name + " TEXT NOT NULL DEFAULT ''")
	return e
}

func (s *GitFootprintStore) Import(ctx context.Context, commits []worktree.ActivityCommit) error {
	if s.err != nil {
		return s.err
	}
	return s.managed.Tx(func(tx *sql.Tx) error {
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
		return nil
	})
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
