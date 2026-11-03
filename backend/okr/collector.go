package okr

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/id"
)

type collectionRetry struct {
	after time.Time
	delay time.Duration
}

func (s *Store) retryReady(key string) bool {
	s.retryMu.Lock()
	defer s.retryMu.Unlock()
	return !s.now().Before(s.retries[key].after)
}

func (s *Store) recordAttempt(key string, err error) {
	s.retryMu.Lock()
	defer s.retryMu.Unlock()
	if err == nil {
		delete(s.retries, key)
		return
	}
	delay := s.retries[key].delay * 2
	if delay == 0 {
		delay = 5 * time.Minute
	}
	if delay > time.Hour {
		delay = time.Hour
	}
	s.retries[key] = collectionRetry{after: s.now().Add(delay), delay: delay}
}

func observed(w *Workspace, m Metric, date string) bool {
	if m.SourceKey == "" {
		return false
	}
	for _, o := range w.Observations {
		if o.MetricID == m.ID && o.SourceKey == m.SourceKey && o.Date == date && o.Source == "github" {
			return true
		}
	}
	return false
}

func (s *Store) Collect(ctx context.Context, github GitHub, projectID string, revision int64, automatic bool) (*Workspace, error) {
	w, err := s.Get(projectID)
	if err != nil {
		return nil, err
	}
	if w == nil {
		return nil, ErrNotFound
	}
	if w.Revision != revision {
		return nil, ErrConflict
	}
	date := today(s.now())
	if automatic && !w.AutoCollect {
		return w, nil
	}
	if date < w.StartDate || date > w.EndDate {
		if automatic {
			return w, nil
		}
		return nil, ErrInvalid
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	counts := map[string]repositoryCounts{}
	failedRepos := map[string]bool{}
	var failures []error
	var additions []Observation
	keys := map[string]string{}
	for _, m := range w.Metrics {
		if m.Source != "github" || (automatic && observed(w, m, date)) {
			continue
		}
		repo := strings.ToLower(m.Repo)
		retryKey := projectID + ":" + repo
		if automatic && !s.retryReady(retryKey) {
			continue
		}
		if failedRepos[repo] {
			continue
		}
		c, ok := counts[repo]
		if !ok {
			c, err = github.fetch(ctx, m.Repo)
			s.recordAttempt(retryKey, err)
			if err != nil {
				if !automatic {
					return nil, err
				}
				failedRepos[repo] = true
				failures = append(failures, err)
				continue
			}
			counts[repo] = c
		}
		key := sourceKey(c.ID, m.Field)
		value := c.Stars
		if m.Field == "forks" {
			value = c.Forks
		}
		keys[m.ID] = key
		additions = append(additions, Observation{ID: id.New(), MetricID: m.ID, Date: date, Value: value, Source: "github", SourceKey: key, CapturedAt: timestamp(s.now())})
	}
	if len(additions) == 0 {
		if len(failures) > 0 {
			return nil, errors.Join(failures...)
		}
		if automatic {
			return w, nil
		}
		return nil, ErrInvalid
	}
	if today(s.now()) != date {
		return nil, ErrSource
	}
	result, err := s.mutate(projectID, revision, false, func(current *Workspace, _ *sql.Tx) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		for i := range current.Metrics {
			if key, ok := keys[current.Metrics[i].ID]; ok {
				current.Metrics[i].SourceKey = key
			}
		}
		current.Observations = append(current.Observations, additions...)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, errors.Join(failures...)
}

// CollectDue uses persisted successful observations as its day-level deduplication ledger.
func (s *Store) CollectDue(ctx context.Context, github GitHub, projectExists func(string) bool) error {
	rows, err := s.db.Query(`SELECT body FROM workspaces`)
	if err != nil {
		return err
	}
	var due []Workspace
	for rows.Next() {
		var body string
		if err = rows.Scan(&body); err != nil {
			rows.Close()
			return err
		}
		var w Workspace
		if err = json.Unmarshal([]byte(body), &w); err != nil {
			rows.Close()
			return err
		}
		if w.AutoCollect {
			due = append(due, w)
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	var failures []error
	for _, w := range due {
		if err := ctx.Err(); err != nil {
			return err
		}
		if projectExists != nil && !projectExists(w.ProjectID) {
			continue
		}
		if _, err := s.Collect(ctx, github, w.ProjectID, w.Revision, true); err != nil && !errors.Is(err, ErrConflict) {
			failures = append(failures, err)
		}
	}
	return errors.Join(failures...)
}

func (s *Store) RunCollector(ctx context.Context, github GitHub, projectExists func(string) bool) {
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()
	for {
		if ctx.Err() != nil {
			return
		}
		if err := s.CollectDue(ctx, github, projectExists); err != nil && ctx.Err() == nil {
			log.Printf("project OKR collection: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
