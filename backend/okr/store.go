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
	db       *storage.DB
	now      func() time.Time
	retryMu  sync.Mutex
	retries  map[string]collectionRetry
	projects func() map[string]string
}

func Open(paths storage.Paths) (*Store, error) {
	if _, err := paths.Ensure(); err != nil {
		return nil, err
	}
	db, err := storage.OpenManaged(paths, storage.DatabaseDescriptor{ID: "project-okr", Kind: "project-okr", Owner: "project-okr", Path: filepath.Join(paths.Database, "project-okr.db")}, []storage.Step{{Version: 1, Name: "project OKR evidence", SQL: `
CREATE TABLE workspaces(project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
CREATE TABLE review_evidence(review_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL);
`}, {Version: 2, Name: "project file ownership", SQL: `CREATE TABLE file_workspaces(project_id TEXT PRIMARY KEY);`}, {Version: 3, Name: "project operation receipts", SQL: `
CREATE TABLE project_operations(
 project_id TEXT NOT NULL,
 operation_key TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('review','observation','memory_append')),
 request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
 intent_json TEXT NOT NULL CHECK(json_valid(intent_json)),
 state TEXT NOT NULL CHECK(state IN ('prepared','applied')),
 receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json)),
 created_at TEXT NOT NULL,
 PRIMARY KEY(project_id,operation_key),
 CHECK((state='prepared' AND receipt_json IS NULL) OR (state='applied' AND receipt_json IS NOT NULL))
);
CREATE TRIGGER project_operation_identity BEFORE UPDATE OF project_id,operation_key,kind,request_sha256,intent_json,created_at ON project_operations BEGIN
 SELECT RAISE(ABORT,'PROJECT_OPERATION_IMMUTABLE');
END;
CREATE TRIGGER project_operation_applied BEFORE UPDATE ON project_operations WHEN OLD.state='applied' BEGIN
 SELECT RAISE(ABORT,'PROJECT_OPERATION_IMMUTABLE');
END;
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

func (s *Store) Get(projectID string) (*Workspace, error) {
	if s.projects != nil {
		return s.getFiles(projectID)
	}
	return read(s.db, projectID)
}

func (s *Store) Evidence(projectID, reviewID string) (*Workspace, error) {
	if s.projects != nil {
		return s.fileEvidence(projectID, reviewID)
	}
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

// Recheck the revision after external reads while holding the write lock.
func (s *Store) mutate(projectID string, revision int64, create bool, change func(*Workspace) error) (*Workspace, error) {
	if s.projects != nil {
		return s.mutateFiles(projectID, revision, create, change, create)
	}
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
		before, err := json.Marshal(w)
		if err != nil {
			return err
		}
		previousReviews := len(w.Reviews)
		if err := change(w); err != nil {
			return err
		}
		for _, review := range w.Reviews[previousReviews:] {
			if _, err := tx.Exec(`INSERT INTO review_evidence(review_id,project_id,revision,body) VALUES(?,?,?,?)`, review.ID, projectID, revision, string(before)); err != nil {
				return err
			}
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
	return s.SaveValidated(projectID, c, nil)
}

// Validate the effective configuration after preserving fields omitted by older clients.
func (s *Store) SaveValidated(projectID string, c Config, validateConfig func(*Config) error) (*Workspace, error) {
	if (c.Dashboard != nil && c.Dashboard.HTML != nil || len(c.Connectors) > 0) && s.projects == nil {
		return nil, ErrInvalid
	}
	if err := validate(&c); err != nil {
		return nil, err
	}
	return s.mutate(projectID, c.Revision, true, func(w *Workspace) error {
		if s.projects != nil && w.Revision > 0 {
			root, err := s.openBundle(projectID, false)
			if err != nil {
				return err
			}
			err = s.decorate(root, w)
			root.Close()
			if err != nil {
				return err
			}
			if w.ProjectFiles.PendingChanges {
				return ErrPending
			}
		}
		applyConfig(w, c)
		if err := validate(&w.Config); err != nil {
			return err
		}
		if len(w.Connectors) > 0 {
			root, err := s.openBundle(projectID, false)
			if err != nil {
				return err
			}
			defer root.Close()
			if err := confirmConnectorPackages(root, &w.Config, true); err != nil {
				return err
			}
		}
		if validateConfig != nil {
			return validateConfig(&w.Config)
		}
		return nil
	})
}

func applyConfig(w *Workspace, c Config) {
	if c.Connectors == nil {
		c.Connectors = w.Connectors
	}
	if c.Team == nil {
		c.Team = w.Team
	}
	if c.Team == nil {
		c.Team = &TeamDefinition{SchemaVersion: 1, Roles: []TeamRole{}}
	}
	if w.Team != nil {
		for i := range c.Team.Roles {
			role := &c.Team.Roles[i]
			if role.MemberID != nil {
				continue
			}
			for _, previous := range w.Team.Roles {
				if previous.ID == role.ID {
					role.MemberID = previous.MemberID
					break
				}
			}
		}
	}
	for i := range c.Metrics {
		m := &c.Metrics[i]
		m.SourceKey = ""
		if connector, field := connectorMetric(&c, m.ID); connector != nil {
			m.SourceKey = connectorSourceKey(*connector, field, *m)
			continue
		}
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
	if c.Dashboard == nil {
		c.Dashboard = w.Dashboard
	}
	if c.Dashboard == nil {
		c.Dashboard = defaultDashboard()
	}
	w.Config = c
}

func (s *Store) Observe(projectID string, revision int64, metricID, date string, value float64, note string) (*Workspace, error) {
	if !validDate(date) || !finite(value) {
		return nil, ErrInvalid
	}
	return s.mutate(projectID, revision, false, func(w *Workspace) error {
		if date < w.StartDate || date > w.EndDate || date > today(s.now()) {
			return ErrInvalid
		}
		for _, m := range w.Metrics {
			if connector, _ := connectorMetric(&w.Config, m.ID); m.ID == metricID && m.Source == "manual" && connector == nil {
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
	return s.mutate(projectID, revision, false, func(w *Workspace) error {
		r := Review{ID: id.New(), Summary: summary, Actions: actions, Date: timestamp(s.now()), EvidenceRevision: w.Revision}
		w.Reviews = append(w.Reviews, r)
		return nil
	})
}
