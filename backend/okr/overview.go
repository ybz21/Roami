package okr

import (
	"encoding/json"
	"time"
)

type EvidencePoint struct {
	Date  string  `json:"date"`
	Value float64 `json:"value"`
}

type ResultOverview struct {
	KeyResult
	Unit     string         `json:"unit"`
	Baseline *EvidencePoint `json:"baseline"`
	Latest   *EvidencePoint `json:"latest"`
	Delta    *float64       `json:"delta"`
}

type Overview struct {
	ProjectID  string           `json:"projectId"`
	Objective  string           `json:"objective"`
	StartDate  string           `json:"startDate"`
	EndDate    string           `json:"endDate"`
	UpdatedAt  string           `json:"updatedAt"`
	Revision   int64            `json:"revision"`
	KeyResults []ResultOverview `json:"keyResults"`
}

func overview(w Workspace) Overview {
	result := Overview{ProjectID: w.ProjectID, Objective: w.Objective, StartDate: w.StartDate, EndDate: w.EndDate, UpdatedAt: w.UpdatedAt, Revision: w.Revision, KeyResults: []ResultOverview{}}
	for _, kr := range w.KeyResults {
		r := ResultOverview{KeyResult: kr}
		for _, m := range w.Metrics {
			if m.ID != kr.MetricID {
				continue
			}
			r.Unit = m.Unit
			key := m.SourceKey
			if key == "" && m.Source == "manual" {
				key = "manual:" + m.ID
			}
			days := map[string]float64{}
			for _, o := range w.Observations {
				if key == "" || o.MetricID != m.ID || o.Source != m.Source || o.SourceKey != key || o.Date < w.StartDate || o.Date > kr.DueDate || !finite(o.Value) {
					continue
				}
				if r.Baseline == nil || o.Date < r.Baseline.Date {
					r.Baseline = &EvidencePoint{Date: o.Date, Value: o.Value}
				}
				if r.Latest == nil || o.Date >= r.Latest.Date {
					r.Latest = &EvidencePoint{Date: o.Date, Value: o.Value}
				}
				days[o.Date] = o.Value
			}
			if r.Latest != nil {
				date, _ := time.Parse(time.DateOnly, r.Latest.Date)
				if previous, ok := days[date.AddDate(0, 0, -1).Format(time.DateOnly)]; ok {
					delta := r.Latest.Value - previous
					r.Delta = &delta
				}
			}
		}
		result.KeyResults = append(result.KeyResults, r)
	}
	return result
}

// Overviews reads only saved objectives; browsing projects never creates a workspace.
func (s *Store) Overviews() ([]Overview, error) {
	rows, err := s.db.Query(`SELECT body FROM workspaces ORDER BY project_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []Overview{}
	for rows.Next() {
		var body string
		if err := rows.Scan(&body); err != nil {
			return nil, err
		}
		var w Workspace
		if err := json.Unmarshal([]byte(body), &w); err != nil {
			return nil, err
		}
		result = append(result, overview(w))
	}
	return result, rows.Err()
}
