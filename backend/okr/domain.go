// Package okr owns project objectives and their recorded evidence.
package okr

import (
	"encoding/json"
	"errors"
	"math"
	"regexp"
	"strings"
	"time"
)

var (
	ErrInvalid  = errors.New("invalid OKR input")
	ErrConflict = errors.New("OKR revision conflict")
	ErrNotFound = errors.New("OKR workspace not found")
	ErrSource   = errors.New("GitHub collection failed")
)

var identifier = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`)
var repository = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$`)

type Metric struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Unit      string `json:"unit"`
	Source    string `json:"source"`
	Repo      string `json:"repo,omitempty"`
	Field     string `json:"field,omitempty"`
	SourceKey string `json:"sourceKey,omitempty"`
}

type KeyResult struct {
	ID       string  `json:"id"`
	Title    string  `json:"title"`
	Horizon  string  `json:"horizon"`
	MetricID string  `json:"metricId"`
	Target   float64 `json:"target"`
	Mode     string  `json:"mode"`
	DueDate  string  `json:"dueDate"`
}

func (k *KeyResult) UnmarshalJSON(b []byte) error {
	type plain KeyResult
	var v struct {
		*plain
		Target *float64 `json:"target"`
	}
	v.plain = (*plain)(k)
	if err := json.Unmarshal(b, &v); err != nil {
		return err
	}
	if v.Target == nil {
		return ErrInvalid
	}
	k.Target = *v.Target
	return nil
}

type Config struct {
	Revision    int64       `json:"revision"`
	Objective   string      `json:"objective"`
	StartDate   string      `json:"startDate"`
	EndDate     string      `json:"endDate"`
	KeyResults  []KeyResult `json:"keyResults"`
	Metrics     []Metric    `json:"metrics"`
	Swarm       string      `json:"swarm"`
	AutoCollect bool        `json:"autoCollect"`
}

type Observation struct {
	ID         string  `json:"id"`
	MetricID   string  `json:"metricId"`
	Date       string  `json:"date"`
	Value      float64 `json:"value"`
	Source     string  `json:"source"`
	SourceKey  string  `json:"sourceKey"`
	CapturedAt string  `json:"capturedAt"`
	Note       string  `json:"note"`
}

type Review struct {
	ID               string `json:"id"`
	Summary          string `json:"summary"`
	Actions          string `json:"actions"`
	Date             string `json:"date"`
	EvidenceRevision int64  `json:"evidenceRevision"`
}

type Workspace struct {
	Config
	ProjectID    string        `json:"projectId"`
	Observations []Observation `json:"observations"`
	Reviews      []Review      `json:"reviews"`
	UpdatedAt    string        `json:"updatedAt"`
}

func validDate(s string) bool {
	d, err := time.Parse(time.DateOnly, s)
	return err == nil && d.Format(time.DateOnly) == s
}

func finite(n float64) bool { return !math.IsNaN(n) && !math.IsInf(n, 0) }

func validate(c *Config) error {
	if c.Revision < 0 || strings.TrimSpace(c.Objective) == "" || !validDate(c.StartDate) || !validDate(c.EndDate) || c.StartDate > c.EndDate || len(c.Metrics) == 0 || len(c.KeyResults) == 0 {
		return ErrInvalid
	}
	metrics := map[string]bool{}
	for i := range c.Metrics {
		m := &c.Metrics[i]
		if !identifier.MatchString(m.ID) || metrics[m.ID] || strings.TrimSpace(m.Name) == "" {
			return ErrInvalid
		}
		metrics[m.ID] = true
		switch m.Source {
		case "manual":
			m.Repo, m.Field = "", ""
		case "github":
			if !repository.MatchString(m.Repo) || strings.HasSuffix(m.Repo, "/.") || strings.HasSuffix(m.Repo, "/..") || (m.Field != "stars" && m.Field != "forks") {
				return ErrInvalid
			}
		default:
			return ErrInvalid
		}
	}
	keys := map[string]bool{}
	for _, k := range c.KeyResults {
		if !identifier.MatchString(k.ID) || keys[k.ID] || strings.TrimSpace(k.Title) == "" || !metrics[k.MetricID] || !finite(k.Target) || !validDate(k.DueDate) || k.DueDate < c.StartDate || k.DueDate > c.EndDate || (k.Horizon != "long" && k.Horizon != "short") || (k.Mode != "increase" && k.Mode != "atLeast" && k.Mode != "atMost") {
			return ErrInvalid
		}
		keys[k.ID] = true
	}
	return nil
}

var shanghai = time.FixedZone("Asia/Shanghai", 8*60*60)

func today(t time.Time) string { return t.In(shanghai).Format(time.DateOnly) }

func timestamp(t time.Time) string { return t.UTC().Format("2006-01-02T15:04:05.000000000Z") }
