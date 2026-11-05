package okr

import (
	"bytes"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"sort"
	"strings"

	"github.com/ybz21/Roami/internal/id"
	"golang.org/x/sys/unix"
)

const bundleRoot = ".roami/okr"
const maxMemory = 64 << 10

//go:embed github.go collector.go store.go
var builtinSources embed.FS

// SetProjects enables project files as the authority; SQLite remains the legacy archive.
// Configure once before serving requests. The callback returns registered IDs and directories.
func (s *Store) SetProjects(projects func() map[string]string) { s.projects = projects }

type confirmedPointer struct {
	SchemaVersion int    `json:"schemaVersion"`
	Revision      int64  `json:"revision"`
	Snapshot      string `json:"snapshot"`
}

type confirmedSnapshot struct {
	Workspace        Workspace            `json:"workspace"`
	Evidence         map[string]Workspace `json:"evidence"`
	ReferenceSources map[string]string    `json:"referenceSources,omitempty"`
}

func (s *Store) workspaces() ([]Workspace, error) {
	result := []Workspace{}
	if s.projects != nil {
		projects := s.projects()
		ids := make([]string, 0, len(projects))
		for id := range projects {
			ids = append(ids, id)
		}
		sort.Strings(ids)
		for _, id := range ids {
			w, err := s.Get(id)
			if err != nil {
				return nil, err
			}
			if w != nil {
				result = append(result, *w)
			}
		}
		return result, nil
	}
	rows, err := s.db.Query(`SELECT body FROM workspaces ORDER BY project_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var body string
		if err := rows.Scan(&body); err != nil {
			return nil, err
		}
		var w Workspace
		if err := json.Unmarshal([]byte(body), &w); err != nil {
			return nil, err
		}
		result = append(result, w)
	}
	return result, rows.Err()
}

func mkdir(root *os.Root, name string) error {
	parts := strings.Split(name, "/")
	for i := range parts {
		p := strings.Join(parts[:i+1], "/")
		info, err := root.Lstat(p)
		if errors.Is(err, fs.ErrNotExist) {
			if err = root.Mkdir(p, 0700); err != nil && !errors.Is(err, fs.ErrExist) {
				return err
			}
			info, err = root.Lstat(p)
		}
		if err != nil {
			return err
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("unsafe OKR directory: %s", p)
		}
	}
	return nil
}

func safeFile(root *os.Root, name string) error {
	if !fs.ValidPath(name) {
		return ErrInvalid
	}
	parts := strings.Split(name, "/")
	for i := range parts {
		info, err := root.Lstat(strings.Join(parts[:i+1], "/"))
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 || (i == len(parts)-1 && !info.Mode().IsRegular()) {
			return fmt.Errorf("unsafe OKR file: %s", name)
		}
	}
	return nil
}

func readFile(root *os.Root, name string, limit int64) ([]byte, error) {
	if err := safeFile(root, name); err != nil {
		return nil, err
	}
	f, err := root.OpenFile(name, os.O_RDONLY|unix.O_NOFOLLOW|unix.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, ErrInvalid
	}
	b, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) > limit {
		return nil, ErrInvalid
	}
	return b, nil
}

// Root-relative rename keeps publication inside the opened directory during path changes.
func atomicFile(root *os.Root, name string, body []byte) error {
	parent := path.Dir(name)
	if err := mkdir(root, parent); err != nil {
		return err
	}
	directory, err := root.OpenRoot(parent)
	if err != nil {
		return err
	}
	defer directory.Close()
	leaf := path.Base(name)
	if _, err := directory.Lstat(leaf); err == nil {
		if err := safeFile(directory, leaf); err != nil {
			return err
		}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	tmp := ".pending-" + id.New()
	f, err := directory.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL|unix.O_NOFOLLOW, 0600)
	if err != nil {
		return err
	}
	defer directory.Remove(tmp)
	if _, err = f.Write(body); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	dir, err := directory.Open(".")
	if err != nil {
		return err
	}
	defer dir.Close()
	if err = unix.Renameat(int(dir.Fd()), tmp, int(dir.Fd()), leaf); err != nil {
		return err
	}
	return dir.Sync()
}

func writeReference(root *os.Root, name string, body []byte, previousDigest string) error {
	if err := mkdir(root, path.Dir(name)); err != nil {
		return err
	}
	f, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL|unix.O_NOFOLLOW, 0600)
	if errors.Is(err, fs.ErrExist) {
		existing, err := readFile(root, name, 1<<20)
		if err != nil {
			return err
		}
		if bytes.Equal(existing, body) {
			return nil
		}
		if previousDigest != "" && hashText(existing) == previousDigest {
			return atomicFile(root, name, body)
		}
		return ErrPending
	}
	if err != nil {
		return err
	}
	_, err = f.Write(body)
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	return closeErr
}

func writeJSON(root *os.Root, name string, value any) error {
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return atomicFile(root, name, append(b, '\n'))
}

func decodeFile(root *os.Root, name string, target any) error {
	b, err := readFile(root, name, 32<<20)
	if err != nil {
		return err
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	if err := d.Decode(target); err != nil {
		return fmt.Errorf("%w: %s", ErrInvalid, name)
	}
	if d.Decode(new(any)) != io.EOF {
		return ErrInvalid
	}
	return nil
}

func (s *Store) marked(projectID string) (bool, error) {
	var count int
	err := s.db.QueryRow(`SELECT count(*) FROM file_workspaces WHERE project_id=?`, projectID).Scan(&count)
	return count > 0, err
}

func (s *Store) openBundle(projectID string, create bool) (*os.Root, error) {
	dir, ok := s.projects()[projectID]
	if !ok {
		return nil, ErrNotFound
	}
	project, err := os.OpenRoot(dir)
	if err != nil {
		return nil, err
	}
	defer project.Close()
	if create {
		if err := mkdir(project, bundleRoot); err != nil {
			return nil, err
		}
	}
	for _, p := range []string{".roami", bundleRoot} {
		info, err := project.Lstat(p)
		if err != nil {
			return nil, err
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, fmt.Errorf("unsafe OKR directory: %s", p)
		}
	}
	return project.OpenRoot(bundleRoot)
}

func lockBundle(root *os.Root) (func(), error) {
	if _, err := root.Lstat(".lock"); err == nil {
		if err := safeFile(root, ".lock"); err != nil {
			return nil, err
		}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	f, err := root.OpenFile(".lock", os.O_CREATE|os.O_RDWR|unix.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, err
	}
	if err = unix.Flock(int(f.Fd()), unix.LOCK_EX); err != nil {
		f.Close()
		return nil, err
	}
	return func() { _ = unix.Flock(int(f.Fd()), unix.LOCK_UN); _ = f.Close() }, nil
}

func loadSnapshot(root *os.Root) (*confirmedSnapshot, error) {
	var pointer confirmedPointer
	if err := decodeFile(root, "state/current.json", &pointer); err != nil {
		return nil, err
	}
	if pointer.SchemaVersion != 1 || pointer.Revision < 1 || !fs.ValidPath(pointer.Snapshot) || path.Dir(pointer.Snapshot) != "state/confirmed-revisions" {
		return nil, ErrInvalid
	}
	var snapshot confirmedSnapshot
	if err := decodeFile(root, pointer.Snapshot, &snapshot); err != nil {
		return nil, err
	}
	if snapshot.Workspace.Revision != pointer.Revision || snapshot.Evidence == nil {
		return nil, ErrInvalid
	}
	seenReviews := map[string]bool{}
	for _, review := range snapshot.Workspace.Reviews {
		evidence, ok := snapshot.Evidence[review.ID]
		if review.ID == "" || seenReviews[review.ID] || !ok || evidence.Revision != review.EvidenceRevision {
			return nil, ErrInvalid
		}
		seenReviews[review.ID] = true
	}
	c := snapshot.Workspace.Config
	if err := validate(&c); err != nil {
		return nil, err
	}
	snapshot.Workspace.Config = c
	return &snapshot, nil
}

func (s *Store) getFiles(projectID string) (*Workspace, error) {
	marked, err := s.marked(projectID)
	if err != nil {
		return nil, err
	}
	root, err := s.openBundle(projectID, false)
	if err != nil {
		if marked || !errors.Is(err, fs.ErrNotExist) {
			return nil, err
		}
		legacy, err := read(s.db, projectID)
		if err != nil || legacy == nil {
			return legacy, err
		}
		return s.migrateFiles(projectID)
	}
	defer root.Close()
	snapshot, err := loadSnapshot(root)
	if err != nil {
		if _, pointerErr := root.Lstat("state/current.json"); pointerErr == nil {
			return nil, err
		}
		if marked || !errors.Is(err, fs.ErrNotExist) {
			return nil, err
		}
		legacy, e := read(s.db, projectID)
		if e != nil {
			return nil, e
		}
		if legacy != nil {
			return s.migrateFiles(projectID)
		}
		return nil, nil
	}
	if !marked {
		if _, err := s.db.Exec(`INSERT OR IGNORE INTO file_workspaces(project_id) VALUES(?)`, projectID); err != nil {
			return nil, err
		}
	}
	w := &snapshot.Workspace
	w.ProjectID = projectID
	if err := s.decorate(root, w); err != nil {
		return nil, err
	}
	return w, nil
}

func (s *Store) migrateFiles(projectID string) (*Workspace, error) {
	root, err := s.openBundle(projectID, true)
	if err != nil {
		return nil, err
	}
	defer root.Close()
	unlock, err := lockBundle(root)
	if err != nil {
		return nil, err
	}
	defer unlock()
	snapshot, err := loadSnapshot(root)
	if err == nil {
		w := &snapshot.Workspace
		w.ProjectID = projectID
		if err := s.decorate(root, w); err != nil {
			return nil, err
		}
		return w, nil
	}
	if !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	marked, err := s.marked(projectID)
	if err != nil {
		return nil, err
	}
	if marked {
		return nil, fmt.Errorf("missing confirmed OKR revision")
	}
	legacy, err := read(s.db, projectID)
	if err != nil || legacy == nil {
		return legacy, err
	}
	if legacy.Dashboard == nil {
		legacy.Dashboard = defaultDashboard()
	}
	evidence := map[string]Workspace{}
	rows, err := s.db.Query(`SELECT review_id,body FROM review_evidence WHERE project_id=?`, projectID)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var key, body string
		if err = rows.Scan(&key, &body); err != nil {
			break
		}
		var w Workspace
		if err = json.Unmarshal([]byte(body), &w); err != nil {
			break
		}
		evidence[key] = w
	}
	rowsErr := rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	if rowsErr != nil {
		return nil, rowsErr
	}
	snapshot = &confirmedSnapshot{Workspace: *legacy, Evidence: evidence}
	if err := publish(root, snapshot, true); err != nil {
		return nil, err
	}
	if _, err := s.db.Exec(`INSERT OR IGNORE INTO file_workspaces(project_id) VALUES(?)`, projectID); err != nil {
		return nil, err
	}
	if err := s.decorate(root, legacy); err != nil {
		return nil, err
	}
	return legacy, nil
}

func hashText(b []byte) string { sum := sha256.Sum256(b); return hex.EncodeToString(sum[:]) }

func workingConfig(root *os.Root) (Config, error) {
	var c Config
	if err := decodeFile(root, "okr.json", &c); err != nil {
		return c, err
	}
	if c.Dashboard != nil {
		return c, ErrInvalid
	}
	var dashboard Dashboard
	if err := decodeFile(root, "dashboard.json", &dashboard); err != nil {
		return c, err
	}
	c.Dashboard = &dashboard
	if c.Team != nil {
		return c, ErrInvalid
	}
	var team TeamDefinition
	if err := decodeFile(root, "agents/team.json", &team); err == nil {
		c.Team = &team
	} else if !errors.Is(err, fs.ErrNotExist) {
		return c, err
	} else if snapshot, err := loadSnapshot(root); err != nil {
		if !errors.Is(err, fs.ErrNotExist) {
			return c, err
		}
	} else if snapshot.Workspace.Team != nil {
		return c, ErrInvalid
	}
	if err := validate(&c); err != nil {
		return c, err
	}
	var main projectMainDefinition
	if err := decodeFile(root, "agents/main.json", &main); err != nil {
		return c, err
	}
	if main.SchemaVersion != 1 || main.Role != "main" {
		return c, ErrInvalid
	}
	if _, err := projectSkills(root, main); err != nil {
		return c, err
	}
	var swarm struct {
		SchemaVersion int    `json:"schemaVersion"`
		SwarmID       string `json:"swarmId"`
	}
	if err := decodeFile(root, "agents/swarm.json", &swarm); err != nil {
		return c, err
	}
	if swarm.SchemaVersion != 1 || c.Swarm != swarm.SwarmID {
		return c, ErrInvalid
	}
	referenceSources := map[string]string{}
	snapshot, err := loadSnapshot(root)
	if err == nil {
		referenceSources = snapshot.ReferenceSources
	} else if !errors.Is(err, fs.ErrNotExist) {
		return c, err
	}
	for _, metric := range c.Metrics {
		var connector connectorDefinition
		if err := decodeFile(root, "connectors/"+metric.ID+"/connector.json", &connector); err != nil {
			return c, err
		}
		sources := []string{"store.go"}
		implementation := "store.go"
		if metric.Source == "github" {
			sources = []string{"github.go", "collector.go"}
			implementation = "github.go"
		}
		if connector.Implementation != implementation {
			return c, ErrInvalid
		}
		for _, source := range sources {
			exported, err := readFile(root, "connectors/"+metric.ID+"/"+source, 1<<20)
			if err != nil {
				return c, err
			}
			compiled, err := builtinSources.ReadFile(source)
			if err != nil {
				return c, err
			}
			digest := referenceSources["connectors/"+metric.ID+"/"+source]
			if digest == "" {
				digest = hashText(compiled)
			}
			if hashText(exported) != digest && !bytes.Equal(exported, compiled) {
				return c, ErrInvalid
			}
		}
		if connector.SchemaVersion != 1 || connector.Execution != "builtin" || connector.Builtin != metric.Source || connector.MetricID != metric.ID || connector.Repo != metric.Repo || connector.Field != metric.Field {
			return c, ErrInvalid
		}
	}
	return c, nil
}

func (s *Store) decorate(root *os.Root, w *Workspace) error {
	if err := s.seedWorkflow(root, w.ProjectID); err != nil {
		return err
	}
	metadata := &ProjectFiles{Root: bundleRoot, SchemaVersion: 1, Revision: w.Revision, MainInstructionsFile: "agents/main.md", TeamMemoryFile: "memory/team.md"}
	workflow, err := readFile(root, "AGENTS.md", maxMemory)
	if err != nil {
		return err
	}
	metadata.WorkflowFile, metadata.Workflow = "AGENTS.md", string(workflow)
	for _, item := range []struct {
		name   string
		target *string
	}{{metadata.MainInstructionsFile, &metadata.MainInstructions}, {metadata.TeamMemoryFile, &metadata.TeamMemory}} {
		b, err := readFile(root, item.name, maxMemory)
		if err != nil {
			return err
		}
		*item.target = string(b)
		if item.name == metadata.TeamMemoryFile {
			metadata.TeamMemorySha256 = hashText(b)
		}
	}
	c, err := workingConfig(root)
	if err != nil {
		metadata.PendingChanges = true
	} else {
		c.Revision = 0
		for i := range c.Metrics {
			c.Metrics[i].SourceKey = ""
		}
		confirmedBytes, _ := json.Marshal(w.Config)
		var confirmed Config
		_ = json.Unmarshal(confirmedBytes, &confirmed)
		confirmed.Revision = 0
		for i := range confirmed.Metrics {
			confirmed.Metrics[i].SourceKey = ""
		}
		a, _ := json.Marshal(c)
		b, _ := json.Marshal(confirmed)
		metadata.PendingChanges = !bytes.Equal(a, b)
	}
	w.ProjectFiles = metadata
	var main projectMainDefinition
	if err := decodeFile(root, "agents/main.json", &main); err == nil {
		metadata.Skills, err = projectSkills(root, main)
		if err != nil {
			metadata.PendingChanges = true
		}
	}
	return nil
}

type connectorDefinition struct {
	SchemaVersion  int    `json:"schemaVersion"`
	MetricID       string `json:"metricId"`
	Execution      string `json:"execution"`
	Builtin        string `json:"builtin"`
	Repo           string `json:"repo,omitempty"`
	Field          string `json:"field,omitempty"`
	Implementation string `json:"implementation"`
}

func definitions(root *os.Root, w *Workspace, referenceSources map[string]string) error {
	config := w.Config
	config.Dashboard = nil
	config.Team = nil
	if err := writeJSON(root, "okr.json", config); err != nil {
		return err
	}
	if err := writeJSON(root, "dashboard.json", w.Dashboard); err != nil {
		return err
	}
	if w.Team != nil {
		if err := writeJSON(root, "agents/team.json", w.Team); err != nil {
			return err
		}
	}
	for _, metric := range w.Metrics {
		file := "connectors/" + metric.ID + "/"
		connector := connectorDefinition{SchemaVersion: 1, MetricID: metric.ID, Execution: "builtin", Builtin: metric.Source, Repo: metric.Repo, Field: metric.Field, Implementation: "README.md"}
		sources := []string{"store.go"}
		connector.Implementation = "store.go"
		if metric.Source == "github" {
			sources = []string{"github.go", "collector.go"}
			connector.Implementation = "github.go"
		}
		for _, source := range sources {
			body, err := builtinSources.ReadFile(source)
			if err != nil {
				return err
			}
			if err := writeReference(root, file+source, body, referenceSources[file+source]); err != nil {
				return err
			}
			referenceSources[file+source] = hashText(body)
		}
		if err := writeJSON(root, file+"connector.json", connector); err != nil {
			return err
		}
		explanation := "Execution: builtin. Values are submitted explicitly through the revision-checked observations API. This file is documentation; edited code is not executed.\n"
		if metric.Source == "github" {
			explanation = "Execution: builtin. The Go GitHub collector calls GET https://api.github.com/repos/{repo}, accepts public repository identity, stars and forks only, refuses redirects, and records source keys github:{repositoryID}:{field}. Editing local code does not change builtin execution.\n"
		}
		if err := atomicFile(root, file+"README.md", []byte(explanation)); err != nil {
			return err
		}
	}
	if err := writeJSON(root, "agents/swarm.json", map[string]any{"schemaVersion": 1, "swarmId": w.Swarm}); err != nil {
		return err
	}
	if err := seedProjectCapabilities(root); err != nil {
		return err
	}
	for _, name := range []string{"memory/team.md", "memory/decisions.md", "memory/decisions.jsonl"} {
		if _, err := root.Lstat(name); errors.Is(err, fs.ErrNotExist) {
			if err := atomicFile(root, name, nil); err != nil {
				return err
			}
		} else if err != nil {
			return err
		} else if err := safeFile(root, name); err != nil {
			return err
		}
	}
	return nil
}

func jsonLines[T any](values []T) ([]byte, error) {
	var b bytes.Buffer
	for _, value := range values {
		if err := json.NewEncoder(&b).Encode(value); err != nil {
			return nil, err
		}
	}
	return b.Bytes(), nil
}

func publish(root *os.Root, snapshot *confirmedSnapshot, writeDefinitions bool) error {
	w := &snapshot.Workspace
	w.ProjectFiles = nil
	if w.Dashboard == nil {
		w.Dashboard = defaultDashboard()
	}
	if snapshot.ReferenceSources == nil {
		snapshot.ReferenceSources = map[string]string{}
	}
	if writeDefinitions {
		if err := definitions(root, w, snapshot.ReferenceSources); err != nil {
			return err
		}
	}
	observations, err := jsonLines(w.Observations)
	if err != nil {
		return err
	}
	reviews, err := jsonLines(w.Reviews)
	if err != nil {
		return err
	}
	for _, item := range []struct {
		name string
		body []byte
	}{{"data/observations.jsonl", observations}, {"data/reviews.jsonl", reviews}} {
		if err := atomicFile(root, item.name, item.body); err != nil {
			return err
		}
	}
	for key, evidence := range snapshot.Evidence {
		name := "evidence/" + key + ".json"
		if !fs.ValidPath(name) || path.Dir(name) != "evidence" {
			return ErrInvalid
		}
		if _, err := root.Lstat(name); err == nil {
			if err := safeFile(root, name); err != nil {
				return err
			}
			continue
		} else if !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		if err := writeJSON(root, name, evidence); err != nil {
			return err
		}
	}
	body, err := json.MarshalIndent(snapshot, "", "  ")
	if err != nil {
		return err
	}
	if len(body) >= 32<<20 {
		return ErrInvalid
	}
	name := fmt.Sprintf("state/confirmed-revisions/%d-%s.json", w.Revision, id.New())
	if err := atomicFile(root, name, append(body, '\n')); err != nil {
		return err
	}
	return writeJSON(root, "state/current.json", confirmedPointer{SchemaVersion: 1, Revision: w.Revision, Snapshot: name})
}

func (s *Store) mutateFiles(projectID string, revision int64, create bool, change func(*Workspace) error, writeDefinitions bool) (*Workspace, error) {
	// Migrate existing evidence before a mutation; a new project gets files only after validation.
	existing, err := s.Get(projectID)
	if err != nil && !(create && errors.Is(err, fs.ErrNotExist)) {
		return nil, err
	}
	if existing == nil && !create {
		return nil, ErrNotFound
	}
	if existing == nil && revision != 0 {
		return nil, ErrConflict
	}
	root, err := s.openBundle(projectID, true)
	if err != nil {
		return nil, err
	}
	defer root.Close()
	unlock, err := lockBundle(root)
	if err != nil {
		return nil, err
	}
	defer unlock()
	snapshot, err := loadSnapshot(root)
	if err != nil {
		if !create || !errors.Is(err, fs.ErrNotExist) {
			return nil, err
		}
		marked, e := s.marked(projectID)
		if e != nil {
			return nil, e
		}
		if marked {
			return nil, fmt.Errorf("missing confirmed OKR revision")
		}
		snapshot = &confirmedSnapshot{Workspace: Workspace{ProjectID: projectID, Observations: []Observation{}, Reviews: []Review{}}, Evidence: map[string]Workspace{}}
	}
	w := &snapshot.Workspace
	w.ProjectID = projectID
	if w.Revision != revision {
		return nil, ErrConflict
	}
	beforeBytes, _ := json.Marshal(w)
	var before Workspace
	if err := json.Unmarshal(beforeBytes, &before); err != nil {
		return nil, err
	}
	reviews := len(w.Reviews)
	if err := change(w); err != nil {
		return nil, err
	}
	for _, review := range w.Reviews[reviews:] {
		snapshot.Evidence[review.ID] = before
	}
	w.Revision++
	w.UpdatedAt = timestamp(s.now())
	if err := publish(root, snapshot, writeDefinitions); err != nil {
		return nil, err
	}
	if _, err := s.db.Exec(`INSERT OR IGNORE INTO file_workspaces(project_id) VALUES(?)`, projectID); err != nil {
		return nil, err
	}
	if err := s.decorate(root, w); err != nil {
		return nil, err
	}
	return w, nil
}

func (s *Store) fileEvidence(projectID, reviewID string) (*Workspace, error) {
	if workspace, err := s.Get(projectID); err != nil {
		return nil, err
	} else if workspace == nil {
		return nil, ErrNotFound
	}
	root, err := s.openBundle(projectID, false)
	if err != nil {
		return nil, err
	}
	defer root.Close()
	snapshot, err := loadSnapshot(root)
	if err != nil {
		return nil, err
	}
	w, ok := snapshot.Evidence[reviewID]
	if !ok {
		return nil, ErrNotFound
	}
	w.ProjectID = projectID
	return &w, nil
}

// Sync confirms editable definitions without accepting replacement observation or review ledgers.
func (s *Store) Sync(projectID string, revision int64) (*Workspace, error) {
	return s.SyncValidated(projectID, revision, nil)
}

func (s *Store) SyncValidated(projectID string, revision int64, validateConfig func(*Config) error) (*Workspace, error) {
	if s.projects == nil {
		return nil, ErrInvalid
	}
	return s.mutateFiles(projectID, revision, true, func(w *Workspace) error {
		root, err := s.openBundle(projectID, false)
		if err != nil {
			return err
		}
		defer root.Close()
		config, err := workingConfig(root)
		if err != nil {
			return err
		}
		config.Revision = revision
		if validateConfig != nil {
			if err := validateConfig(&config); err != nil {
				return err
			}
		}
		applyConfig(w, config)
		return validate(&w.Config)
	}, true)
}

func (s *Store) WriteMemory(projectID, content, expectedSha256 string) (*Workspace, error) {
	if s.projects == nil || len(content) > maxMemory || len(expectedSha256) != 64 {
		return nil, ErrInvalid
	}
	w, err := s.Get(projectID)
	if err != nil {
		return nil, err
	}
	if w == nil {
		return nil, ErrNotFound
	}
	root, err := s.openBundle(projectID, false)
	if err != nil {
		return nil, err
	}
	defer root.Close()
	unlock, err := lockBundle(root)
	if err != nil {
		return nil, err
	}
	b, err := readFile(root, "memory/team.md", maxMemory)
	if err == nil && hashText(b) != expectedSha256 {
		err = ErrConflict
	}
	if err == nil {
		err = atomicFile(root, "memory/team.md", []byte(content))
	}
	unlock()
	if err != nil {
		return nil, err
	}
	return s.Get(projectID)
}
