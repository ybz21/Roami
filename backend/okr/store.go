package okr

import (
	"database/sql"
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/id"
	storage "github.com/ybz21/Roami/internal/storage"
)

type Store struct {
	db      *storage.DB
	now     func() time.Time
	retryMu sync.Mutex
	retries map[string]collectionRetry
}

func Open(paths storage.Paths) (*Store, error) {
	if _, err := paths.Ensure(); err != nil {
		return nil, err
	}
	db, err := storage.OpenManaged(paths, storage.DatabaseDescriptor{ID: "project-okr", Kind: "project-okr", Owner: "project-okr", Path: filepath.Join(paths.Database, "project-okr.db")}, []storage.Step{{Version: 1, Name: "project OKR evidence", SQL: `
CREATE TABLE workspaces(project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
CREATE TABLE review_evidence(review_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL);
`}}, storage.Options{})
	if err != nil {
		return nil, err
	}
	return &Store{db: db, now: time.Now, retries: map[string]collectionRetry{}}, nil
}

type rowReader interface{ QueryRow(string, ...any) *sql.Row }

func read(q rowReader, projectID string) (*Workspace, error) {
	var body string
	err := q.QueryRow(`SELECT body FROM workspaces WHERE project_id=?`, projectID).Scan(&body)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var w Workspace
	if err := json.Unmarshal([]byte(body), &w); err != nil {
		return nil, err
	}
	return &w, nil
}

func (s *Store) Get(projectID string) (*Workspace, error) { return read(s.db, projectID) }

func (s *Store) Evidence(projectID, reviewID string) (*Workspace, error) {
	var body string
	err := s.db.QueryRow(`SELECT body FROM review_evidence WHERE project_id=? AND review_id=?`, projectID, reviewID).Scan(&body)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	var w Workspace
	if err := json.Unmarshal([]byte(body), &w); err != nil {
		return nil, err
	}
	return &w, nil
}

// The revision is checked again after external reads, inside the write transaction.
func (s *Store) mutate(projectID string, revision int64, create bool, change func(*Workspace, *sql.Tx) error) (*Workspace, error) {
	var result *Workspace
	err := s.db.Tx(func(tx *sql.Tx) error {
		w, err := read(tx, projectID)
		if err != nil {
			return err
		}
		if w == nil {
			if !create {
				return ErrNotFound
			}
			w = &Workspace{ProjectID: projectID, Observations: []Observation{}, Reviews: []Review{}}
		}
		if w.Revision != revision {
			return ErrConflict
		}
		if err := change(w, tx); err != nil {
			return err
		}
		w.Revision++
		w.UpdatedAt = timestamp(s.now())
		body, err := json.Marshal(w)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(`INSERT INTO workspaces(project_id,revision,body) VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision,body=excluded.body`, projectID, w.Revision, string(body)); err != nil {
			return err
		}
		result = w
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (s *Store) Save(projectID string, c Config) (*Workspace, error) {
	if err := validate(&c); err != nil {
		return nil, err
	}
	return s.mutate(projectID, c.Revision, true, func(w *Workspace, _ *sql.Tx) error {
		for i := range c.Metrics {
			m := &c.Metrics[i]
			m.SourceKey = ""
			if m.Source == "manual" {
				m.SourceKey = "manual:" + m.ID
				continue
			}
			for _, old := range w.Metrics {
				if old.ID == m.ID && old.Source == m.Source && strings.EqualFold(old.Repo, m.Repo) && old.Field == m.Field {
					m.SourceKey = old.SourceKey
				}
			}
		}
		w.Config = c
		return nil
	})
}

func (s *Store) Observe(projectID string, revision int64, metricID, date string, value float64, note string) (*Workspace, error) {
	if !validDate(date) || !finite(value) {
		return nil, ErrInvalid
	}
	return s.mutate(projectID, revision, false, func(w *Workspace, _ *sql.Tx) error {
		if date < w.StartDate || date > w.EndDate || date > today(s.now()) {
			return ErrInvalid
		}
		for _, m := range w.Metrics {
			if m.ID == metricID && m.Source == "manual" {
				w.Observations = append(w.Observations, Observation{ID: id.New(), MetricID: m.ID, Date: date, Value: value, Source: "manual", SourceKey: m.SourceKey, CapturedAt: timestamp(s.now()), Note: note})
				return nil
			}
		}
		return ErrInvalid
	})
}

func (s *Store) Review(projectID string, revision int64, summary, actions string) (*Workspace, error) {
	if strings.TrimSpace(summary) == "" {
		return nil, ErrInvalid
	}
	return s.mutate(projectID, revision, false, func(w *Workspace, tx *sql.Tx) error {
		r := Review{ID: id.New(), Summary: summary, Actions: actions, Date: timestamp(s.now()), EvidenceRevision: w.Revision}
		// Preserve the evidence even when later configuration edits change the interpretation.
		evidence, err := json.Marshal(w)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(`INSERT INTO review_evidence(review_id,project_id,revision,body) VALUES(?,?,?,?)`, r.ID, projectID, w.Revision, string(evidence)); err != nil {
			return err
		}
		w.Reviews = append(w.Reviews, r)
		return nil
	})
}
