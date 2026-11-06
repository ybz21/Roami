package okr

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/id"
)

type ConnectorBatchValue struct {
	MetricID string   `json:"metricId"`
	Unit     *string  `json:"unit"`
	Value    *float64 `json:"value"`
}

type ConnectorBatchEvidence struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}

type ConnectorBatch struct {
	ID             string                   `json:"id"`
	ConnectorID    string                   `json:"connectorId"`
	PackageSHA256  string                   `json:"packageSha256"`
	SourceIdentity string                   `json:"sourceIdentity"`
	Date           string                   `json:"date"`
	CapturedAt     string                   `json:"capturedAt"`
	WindowStart    string                   `json:"windowStart"`
	WindowEnd      string                   `json:"windowEnd"`
	Note           string                   `json:"note,omitempty"`
	Values         []ConnectorBatchValue    `json:"values"`
	Evidence       []ConnectorBatchEvidence `json:"evidence"`
}

type ConnectorEvidenceReceipt struct {
	ConnectorBatchEvidence
	Archive string `json:"archive"`
	Bytes   int    `json:"bytes"`
}

type ConnectorBatchReceipt struct {
	ID             string                     `json:"id"`
	ConnectorID    string                     `json:"connectorId"`
	PackageSHA256  string                     `json:"packageSha256"`
	SourceIdentity string                     `json:"sourceIdentity"`
	RequestSHA256  string                     `json:"requestSha256"`
	Revision       int64                      `json:"revision"`
	PublishedAt    string                     `json:"publishedAt"`
	CapturedAt     string                     `json:"capturedAt"`
	Date           string                     `json:"date"`
	WindowStart    string                     `json:"windowStart"`
	WindowEnd      string                     `json:"windowEnd"`
	ObservationIDs []string                   `json:"observationIds"`
	Evidence       []ConnectorEvidenceReceipt `json:"evidence"`
}

func batchReplay(w *Workspace, batchID, digest string) (bool, error) {
	if w == nil {
		return false, ErrNotFound
	}
	for _, receipt := range w.ConnectorBatches {
		if receipt.ID == batchID {
			if receipt.RequestSHA256 != digest {
				return false, ErrConflict
			}
			return true, nil
		}
	}
	return false, nil
}

// Reconcile a committed batch after an uncertain result without replaying a write.
func (s *Store) RecordConnectorBatch(projectID string, revision int64, batch ConnectorBatch) (*Workspace, error) {
	if s.projects == nil || revision < 0 || !memberIdentity.MatchString(batch.ID) {
		return nil, ErrInvalid
	}
	body, err := json.Marshal(struct {
		Revision int64          `json:"revision"`
		Batch    ConnectorBatch `json:"batch"`
	}{revision, batch})
	if err != nil {
		return nil, ErrInvalid
	}
	digest := hashText(body)
	current, err := s.Get(projectID)
	if err != nil {
		return nil, err
	}
	if replay, err := batchReplay(current, batch.ID, digest); err != nil || replay {
		return current, err
	}
	result, err := s.mutate(projectID, revision, false, func(w *Workspace) error {
		root, err := s.openBundle(projectID, false)
		if err != nil {
			return err
		}
		defer root.Close()
		return s.appendConnectorBatch(root, w, batch, digest)
	})
	if err == nil {
		return result, nil
	}
	observed, readErr := s.Get(projectID)
	if readErr == nil {
		replay, replayErr := batchReplay(observed, batch.ID, digest)
		if replay || errors.Is(replayErr, ErrConflict) {
			return observed, replayErr
		}
	}
	return nil, err
}

func (s *Store) appendConnectorBatch(root *os.Root, w *Workspace, batch ConnectorBatch, requestDigest string) error {
	var connector *SkillConnector
	for i := range w.Connectors {
		if w.Connectors[i].ID == batch.ConnectorID {
			connector = &w.Connectors[i]
			break
		}
	}
	if connector == nil || batch.SourceIdentity != connector.Identity || !validDigest(batch.PackageSHA256) || batch.PackageSHA256 != connector.PackageSHA256 || len(batch.Values) == 0 || len(batch.Values) > 64 || len(batch.Evidence) == 0 || len(batch.Evidence) > 8 || len(batch.Note) > 4000 {
		return ErrInvalid
	}
	digest, err := connectorPackage(root, *connector)
	if err != nil {
		return err
	}
	if digest != connector.PackageSHA256 {
		return ErrPending
	}
	captured, err := time.Parse(time.RFC3339Nano, batch.CapturedAt)
	if err != nil || captured.After(s.now()) {
		return ErrInvalid
	}
	start, startErr := time.Parse(time.RFC3339Nano, batch.WindowStart)
	end, endErr := time.Parse(time.RFC3339Nano, batch.WindowEnd)
	zone, zoneErr := time.LoadLocation(connector.Timezone)
	if startErr != nil || endErr != nil || zoneErr != nil || start.After(end) || end.After(captured) || !validDate(batch.Date) || batch.Date < w.StartDate || batch.Date > w.EndDate {
		return ErrInvalid
	}
	if connector.Window == "snapshot" {
		if !start.Equal(end) || batch.Date != end.In(zone).Format(time.DateOnly) || connector.Service == "github" && !captured.Equal(end) {
			return ErrInvalid
		}
	} else {
		day, _ := time.ParseInLocation(time.DateOnly, batch.Date, zone)
		if !start.Equal(day) || !end.After(start) || end.After(day.AddDate(0, 0, 1)) {
			return ErrInvalid
		}
	}
	project, err := os.OpenRoot(s.projects()[w.ProjectID])
	if err != nil {
		return err
	}
	defer project.Close()
	evidence := make([]ConnectorEvidenceReceipt, 0, len(batch.Evidence))
	bodies, paths, total := [][]byte{}, map[string]bool{}, 0
	for _, item := range batch.Evidence {
		if !fs.ValidPath(item.Path) || strings.ContainsAny(item.Path, `\:%?#`) || !validDigest(item.SHA256) || paths[item.Path] {
			return ErrInvalid
		}
		body, err := readFile(project, item.Path, 4<<20)
		if err != nil {
			return err
		}
		total += len(body)
		if total > 8<<20 || hashText(body) != item.SHA256 {
			return ErrInvalid
		}
		paths[item.Path] = true
		bodies = append(bodies, body)
		evidence = append(evidence, ConnectorEvidenceReceipt{item, path.Join("state/connector-evidence", item.SHA256), len(body)})
	}
	metrics, fields := map[string]Metric{}, map[string]string{}
	for _, m := range w.Metrics {
		metrics[m.ID] = m
	}
	for _, binding := range connector.Bindings {
		fields[binding.MetricID] = binding.Field
	}
	additions, seen := []Observation{}, map[string]bool{}
	for _, candidate := range batch.Values {
		metric, exists := metrics[candidate.MetricID]
		if !exists || fields[metric.ID] == "" || seen[metric.ID] || candidate.Value == nil || !finite(*candidate.Value) || candidate.Unit == nil || *candidate.Unit != metric.Unit {
			return ErrInvalid
		}
		if connector.Service == "github" && !githubBatchValue(*connector, fields[metric.ID], *candidate.Value, bodies) {
			return ErrInvalid
		}
		key := connectorSourceKey(*connector, fields[metric.ID], metric)
		if key != metric.SourceKey {
			return ErrInvalid
		}
		additions = append(additions, Observation{ID: id.New(), MetricID: metric.ID, Date: batch.Date, Value: *candidate.Value, Source: metric.Source, SourceKey: key, CapturedAt: timestamp(captured), Note: batch.Note, ConnectorID: connector.ID, BatchID: batch.ID})
		seen[metric.ID] = true
	}
	// Immutable copies are referenced only when the confirmed snapshot pointer commits.
	for i, item := range evidence {
		body, err := readFile(root, item.Archive, 4<<20)
		if err == nil {
			if hashText(body) != item.SHA256 {
				return ErrInvalid
			}
		} else if !errors.Is(err, fs.ErrNotExist) {
			return err
		} else if err := atomicFile(root, item.Archive, bodies[i]); err != nil {
			return err
		}
	}
	receipt := ConnectorBatchReceipt{ID: batch.ID, ConnectorID: connector.ID, PackageSHA256: digest, SourceIdentity: connector.Identity, RequestSHA256: requestDigest, Revision: w.Revision + 1, PublishedAt: timestamp(s.now()), CapturedAt: timestamp(captured), Date: batch.Date, WindowStart: timestamp(start), WindowEnd: timestamp(end), ObservationIDs: []string{}, Evidence: evidence}
	for _, observation := range additions {
		receipt.ObservationIDs = append(receipt.ObservationIDs, observation.ID)
	}
	w.Observations = append(w.Observations, additions...)
	w.ConnectorBatches = append(w.ConnectorBatches, receipt)
	return nil
}

func githubBatchValue(connector SkillConnector, field string, value float64, bodies [][]byte) bool {
	for _, body := range bodies {
		var source struct {
			ID      json.Number `json:"id"`
			Repo    string      `json:"full_name"`
			Private *bool       `json:"private"`
			Stars   *int64      `json:"stargazers_count"`
			Forks   *int64      `json:"forks_count"`
		}
		if json.Unmarshal(body, &source) != nil || string(source.ID) != connector.Identity || !strings.EqualFold(source.Repo, connector.Repo) || source.Private == nil || *source.Private {
			continue
		}
		count := source.Stars
		if field == "forks" {
			count = source.Forks
		}
		if count != nil && *count >= 0 && *count <= 9007199254740991 && float64(*count) == value {
			return true
		}
	}
	return false
}
