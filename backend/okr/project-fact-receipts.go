package okr

import (
	"strings"

	"github.com/ybz21/Roami/internal/id"
)

func (s *Store) ReviewOnce(projectID, key string, revision int64, summary, actions string) (*Workspace, error) {
	if strings.TrimSpace(summary) == "" {
		return nil, ErrInvalid
	}
	digest, err := operationDigest(key, "review", struct{ Summary, Actions string }{summary, actions})
	if err != nil {
		return nil, err
	}
	root, close, err := s.operationRoot(projectID)
	if err != nil {
		return nil, err
	}
	defer close()
	snapshot, err := loadSnapshot(root)
	if err != nil {
		return nil, err
	}
	op, err := s.readOperation(projectID, key, "review", digest)
	if err != nil {
		return nil, err
	}
	if op != nil && op.Receipt != nil {
		return s.operationWorkspace(projectID, op.Receipt)
	}
	if op == nil {
		if snapshot.Workspace.Revision != revision {
			return nil, ErrConflict
		}
		op = &projectOperation{Key: key, Kind: "review", RequestSHA256: digest, Intent: projectOperationIntent{Revision: revision, Review: &Review{ID: id.New(), Summary: summary, Actions: actions, Date: timestamp(s.now()), EvidenceRevision: revision}}}
		if err := s.prepareOperation(projectID, op); err != nil {
			return nil, err
		}
	}
	if op.Intent.Review == nil {
		return nil, ErrInvalid
	}
	for _, actual := range snapshot.Workspace.Reviews {
		if actual.ID == op.Intent.Review.ID {
			if actual != *op.Intent.Review {
				return nil, ErrConflict
			}
			return s.finishOperation(projectID, op)
		}
	}
	if snapshot.Workspace.Revision != op.Intent.Revision {
		return nil, ErrConflict
	}
	_, err = s.mutateFilesLocked(root, projectID, op.Intent.Revision, false, func(w *Workspace) error {
		w.Reviews = append(w.Reviews, *op.Intent.Review)
		return nil
	}, false)
	if err != nil {
		return nil, err
	}
	return s.finishOperation(projectID, op)
}

func (s *Store) ObserveOnce(projectID, key string, revision int64, metricID, date string, value float64, note string) (*Workspace, error) {
	if !validDate(date) || !finite(value) {
		return nil, ErrInvalid
	}
	digest, err := operationDigest(key, "observation", struct {
		MetricID, Date string
		Value          float64
		Note           string
	}{metricID, date, value, note})
	if err != nil {
		return nil, err
	}
	root, close, err := s.operationRoot(projectID)
	if err != nil {
		return nil, err
	}
	defer close()
	snapshot, err := loadSnapshot(root)
	if err != nil {
		return nil, err
	}
	op, err := s.readOperation(projectID, key, "observation", digest)
	if err != nil {
		return nil, err
	}
	if op != nil && op.Receipt != nil {
		return s.operationWorkspace(projectID, op.Receipt)
	}
	if op == nil {
		w := &snapshot.Workspace
		if w.Revision != revision {
			return nil, ErrConflict
		}
		if date < w.StartDate || date > w.EndDate || date > today(s.now()) {
			return nil, ErrInvalid
		}
		var observation *Observation
		for _, metric := range w.Metrics {
			if connector, _ := connectorMetric(&w.Config, metric.ID); metric.ID == metricID && metric.Source == "manual" && connector == nil {
				observation = &Observation{ID: id.New(), MetricID: metric.ID, Date: date, Value: value, Source: "manual", SourceKey: metric.SourceKey, CapturedAt: timestamp(s.now()), Note: note}
				break
			}
		}
		if observation == nil {
			return nil, ErrInvalid
		}
		op = &projectOperation{Key: key, Kind: "observation", RequestSHA256: digest, Intent: projectOperationIntent{Revision: revision, Observation: observation}}
		if err := s.prepareOperation(projectID, op); err != nil {
			return nil, err
		}
	}
	if op.Intent.Observation == nil {
		return nil, ErrInvalid
	}
	for _, actual := range snapshot.Workspace.Observations {
		if actual.ID == op.Intent.Observation.ID {
			if actual != *op.Intent.Observation {
				return nil, ErrConflict
			}
			return s.finishOperation(projectID, op)
		}
	}
	if snapshot.Workspace.Revision != op.Intent.Revision {
		return nil, ErrConflict
	}
	_, err = s.mutateFilesLocked(root, projectID, op.Intent.Revision, false, func(w *Workspace) error {
		w.Observations = append(w.Observations, *op.Intent.Observation)
		return nil
	}, false)
	if err != nil {
		return nil, err
	}
	return s.finishOperation(projectID, op)
}
