// Package okr owns project objectives and their recorded evidence.
package okr

import (
	"encoding/json"
	"errors"
	"math"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

var (
	ErrInvalid  = errors.New("invalid OKR input")
	ErrConflict = errors.New("OKR revision conflict")
	ErrNotFound = errors.New("OKR workspace not found")
	ErrPending  = errors.New("OKR project files have pending changes")
	ErrSource   = errors.New("GitHub collection failed")
)

var memberIdentity = regexp.MustCompile(`^[a-f0-9]{32}$`)
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

type Initiative struct {
	ID           string   `json:"id"`
	Title        string   `json:"title"`
	Channel      string   `json:"channel"`
	KeyResultIDs []string `json:"keyResultIds"`
	Description  string   `json:"description"`
	Acceptance   string   `json:"acceptance"`
}

type DashboardWidget struct {
	ID           string   `json:"id"`
	Type         string   `json:"type"`
	KeyResultIDs []string `json:"keyResultIds,omitempty"`
	MetricIDs    []string `json:"metricIds,omitempty"`
	Title        string   `json:"title,omitempty"`
}

type Dashboard struct {
	SchemaVersion int               `json:"schemaVersion"`
	Widgets       []DashboardWidget `json:"widgets"`
}

type TeamRole struct {
	MemberID *string `json:"memberId,omitempty"`
	ID       string  `json:"id"`
	Name     string  `json:"name"`
	Executor string  `json:"executor"`
	Duty     string  `json:"duty"`
}

type TeamDefinition struct {
	SchemaVersion int        `json:"schemaVersion"`
	Roles         []TeamRole `json:"roles"`
}

type ProjectFiles struct {
	TeamRoleBindings     bool           `json:"teamRoleBindings,omitempty"`
	Root                 string         `json:"root"`
	SchemaVersion        int            `json:"schemaVersion"`
	Revision             int64          `json:"revision"`
	MainInstructionsFile string         `json:"mainInstructionsFile"`
	TeamMemoryFile       string         `json:"teamMemoryFile"`
	MainInstructions     string         `json:"mainInstructions,omitempty"`
	WorkflowFile         string         `json:"workflowFile,omitempty"`
	Workflow             string         `json:"workflow,omitempty"`
	TeamMemory           string         `json:"teamMemory,omitempty"`
	TeamMemorySha256     string         `json:"teamMemorySha256"`
	PendingChanges       bool           `json:"pendingChanges"`
	Skills               []ProjectSkill `json:"skills"`
}

type ProjectSkill struct {
	ID      string `json:"id"`
	Path    string `json:"path"`
	Content string `json:"content"`
	SHA256  string `json:"sha256"`
}

type Config struct {
	Team        *TeamDefinition `json:"team,omitempty"`
	Initiatives []Initiative    `json:"initiatives,omitempty"`
	Dashboard   *Dashboard      `json:"dashboard,omitempty"`
	Revision    int64           `json:"revision"`
	Objective   string          `json:"objective"`
	StartDate   string          `json:"startDate"`
	EndDate     string          `json:"endDate"`
	KeyResults  []KeyResult     `json:"keyResults"`
	Metrics     []Metric        `json:"metrics"`
	Swarm       string          `json:"swarm"`
	AutoCollect bool            `json:"autoCollect"`
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
	ProjectFiles *ProjectFiles `json:"projectFiles,omitempty"`
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
	if c.Team != nil {
		if c.Team.SchemaVersion != 1 || c.Team.Roles == nil || len(c.Team.Roles) > 64 {
			return ErrInvalid
		}
		ids, names, members := map[string]bool{}, map[string]bool{}, map[string]bool{}
		for _, role := range c.Team.Roles {
			if role.MemberID != nil && *role.MemberID != "" {
				if !memberIdentity.MatchString(*role.MemberID) || c.Swarm == "" || members[*role.MemberID] {
					return ErrInvalid
				}
				members[*role.MemberID] = true
			}
			name := strings.TrimSpace(role.Name)
			if !identifier.MatchString(role.ID) || ids[role.ID] || name == "" || name != role.Name || names[name] || utf8.RuneCountInString(name) > 80 || strings.EqualFold(name, "main") || strings.EqualFold(name, "leader") || strings.TrimSpace(role.Duty) == "" || utf8.RuneCountInString(role.Duty) > 8000 {
				return ErrInvalid
			}
			switch role.Executor {
			case "native", "codex", "claude", "opencode", "pi":
			default:
				return ErrInvalid
			}
			ids[role.ID], names[name] = true, true
		}
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
	initiatives := map[string]bool{}
	for _, initiative := range c.Initiatives {
		if !identifier.MatchString(initiative.ID) || initiatives[initiative.ID] || strings.TrimSpace(initiative.Title) == "" || strings.TrimSpace(initiative.Channel) == "" {
			return ErrInvalid
		}
		initiatives[initiative.ID] = true
		seen := map[string]bool{}
		for _, key := range initiative.KeyResultIDs {
			if !keys[key] || seen[key] {
				return ErrInvalid
			}
			seen[key] = true
		}
	}
	if c.Dashboard != nil {
		if c.Dashboard.SchemaVersion != 1 || c.Dashboard.Widgets == nil {
			return ErrInvalid
		}
		seen := map[string]bool{}
		for _, widget := range c.Dashboard.Widgets {
			if !identifier.MatchString(widget.ID) || seen[widget.ID] {
				return ErrInvalid
			}
			seen[widget.ID] = true
			switch widget.Type {
			case "keyResults", "metricTrend", "nextAction":
			default:
				return ErrInvalid
			}
			for _, key := range widget.KeyResultIDs {
				if !keys[key] {
					return ErrInvalid
				}
			}
			for _, metric := range widget.MetricIDs {
				if !metrics[metric] {
					return ErrInvalid
				}
			}
		}
	}
	return nil
}

func defaultDashboard() *Dashboard {
	return &Dashboard{SchemaVersion: 1, Widgets: []DashboardWidget{{ID: "results", Type: "keyResults"}, {ID: "trends", Type: "metricTrend"}, {ID: "next", Type: "nextAction"}}}
}

var shanghai = time.FixedZone("Asia/Shanghai", 8*60*60)

func today(t time.Time) string { return t.In(shanghai).Format(time.DateOnly) }

func timestamp(t time.Time) string { return t.UTC().Format("2006-01-02T15:04:05.000000000Z") }
