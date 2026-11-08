package okr

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
)

func connectorFixture(t *testing.T, github bool) (*Store, string, *Workspace, ConnectorBatch) {
	t.Helper()
	s, project := fileStore(t)
	config := testConfig()
	if github {
		config = githubConfig()
	}
	w, err := s.Save("project", config)
	if err != nil {
		t.Fatal(err)
	}
	if !github {
		w, err = s.Observe("project", w.Revision, "users", "2026-11-03", 3, "Prior explicit observation")
		if err != nil {
			t.Fatal(err)
		}
	}
	pkg := filepath.Join(project, ".roami/okr/connectors/source")
	if err := os.MkdirAll(filepath.Join(pkg, "scripts"), 0700); err != nil {
		t.Fatal(err)
	}
	for name, body := range map[string]string{"SKILL.md": "---\nname: source\ndescription: Collect scoped source evidence.\n---\nRead current binding before collection.\n", "scripts/fetch.py": "print('candidate only')\n"} {
		if err := os.WriteFile(filepath.Join(pkg, name), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
	}
	connector := SkillConnector{ID: "source", Name: "Source workflow", Service: "mcp", Identity: "account-one", Timezone: "Asia/Shanghai", Window: "day", Files: []string{"SKILL.md", "scripts/fetch.py"}, Bindings: []ConnectorMetric{{MetricID: "users", Field: "users"}}}
	body := []byte(`{"account":"account-one","users":0}`)
	if github {
		connector.Service, connector.Identity, connector.Repo, connector.Window, connector.Bindings[0].Field = "github", "42", "owner/project", "snapshot", "stars"
		body = []byte(`{"id":42,"full_name":"owner/project","private":false,"stargazers_count":0,"forks_count":3}`)
	}
	config = w.Config
	config.Connectors = []SkillConnector{connector}
	w, err = s.Save("project", config)
	if err != nil {
		t.Fatal(err)
	}
	foundSource := false
	for _, skill := range w.ProjectFiles.Skills {
		if skill.ID == "connector-source" && skill.Path == "connectors/source/SKILL.md" {
			foundSource = true
		}
	}
	if w.ProjectFiles.PendingChanges || !w.ProjectFiles.ConnectorSkillBatches || !foundSource {
		t.Fatalf("missing confirmed Skill: %+v", w.ProjectFiles)
	}
	evidence := "evidence/source-response.json"
	if err := os.MkdirAll(filepath.Dir(filepath.Join(project, evidence)), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(project, evidence), body, 0600); err != nil {
		t.Fatal(err)
	}
	unit, zero := w.Metrics[0].Unit, 0.0
	batch := ConnectorBatch{ID: strings.Repeat("a", 32), ConnectorID: "source", SourceIdentity: connector.Identity, PackageSHA256: w.Connectors[0].PackageSHA256, Date: "2026-11-03", CapturedAt: "2026-11-02T16:20:00Z", WindowStart: "2026-11-02T16:00:00Z", WindowEnd: "2026-11-02T16:20:00Z", Values: []ConnectorBatchValue{{MetricID: "users", Unit: &unit, Value: &zero}}, Evidence: []ConnectorBatchEvidence{{Path: evidence, SHA256: hashText(body)}}}
	if github {
		batch.WindowStart = batch.WindowEnd
	}
	return s, project, w, batch
}

func TestConnectorBatchCommitReplayAndFileRecovery(t *testing.T) {
	s, project, before, batch := connectorFixture(t, false)
	after, err := s.RecordConnectorBatch("project", before.Revision, batch)
	if err != nil {
		t.Fatal(err)
	}
	if after.Revision != before.Revision+1 || len(after.Observations) != len(before.Observations)+1 || after.Observations[1].Value != 0 || after.Observations[1].BatchID != batch.ID || after.Observations[1].SourceKey == "manual:users" {
		t.Fatal("batch lost zero or source identity", after)
	}
	receipt := after.ConnectorBatches[0]
	archived, err := os.ReadFile(filepath.Join(project, ".roami/okr", receipt.Evidence[0].Archive))
	if err != nil || hashText(archived) != batch.Evidence[0].SHA256 || receipt.Revision != after.Revision || len(receipt.ObservationIDs) != 1 {
		t.Fatal("missing immutable evidence", receipt, err)
	}
	if err := os.Remove(filepath.Join(project, batch.Evidence[0].Path)); err != nil {
		t.Fatal(err)
	}
	replay, err := s.RecordConnectorBatch("project", before.Revision, batch)
	if err != nil || replay.Revision != after.Revision || !reflect.DeepEqual(replay.ConnectorBatches, after.ConnectorBatches) {
		t.Fatal("unknown outcome retry wrote again", replay, err)
	}
	if _, err := s.RecordConnectorBatch("project", after.Revision, batch); !errors.Is(err, ErrConflict) {
		t.Fatal("same key with another request was accepted", err)
	}
	recovered, _ := testStore(t)
	recovered.SetProjects(func() map[string]string { return map[string]string{"project": project} })
	restored, err := recovered.Get("project")
	if err != nil || !reflect.DeepEqual(restored, after) {
		t.Fatal("new database lost facts/receipts", restored, err)
	}
	replay, err = recovered.RecordConnectorBatch("project", before.Revision, batch)
	if err != nil || replay.Revision != after.Revision {
		t.Fatal("recovery lost deduplication", err)
	}
}

func TestConnectorBatchConcurrentRetryPublishesOnce(t *testing.T) {
	s, _, before, batch := connectorFixture(t, true)
	var group sync.WaitGroup
	for i := 0; i < 5; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			if _, err := s.RecordConnectorBatch("project", before.Revision, batch); err != nil {
				t.Error(err)
			}
		}()
	}
	group.Wait()
	current, err := s.Get("project")
	if err != nil || current.Revision != before.Revision+1 || len(current.Observations) != 1 || len(current.ConnectorBatches) != 1 || current.Metrics[0].SourceKey != "github:42:stars" {
		t.Fatal(current, err)
	}
}

func TestConnectorBatchRejectsInvalidEvidenceWithoutChangingFacts(t *testing.T) {
	for _, name := range []string{"unit", "metric", "duplicate", "null", "source", "package", "evidence", "path", "future", "window", "date", "script"} {
		t.Run(name, func(t *testing.T) {
			s, project, before, batch := connectorFixture(t, false)
			pointer := filepath.Join(project, ".roami/okr/state/current.json")
			original, err := os.ReadFile(pointer)
			if err != nil {
				t.Fatal(err)
			}
			switch name {
			case "unit":
				value := "seconds"
				batch.Values[0].Unit = &value
			case "metric":
				batch.Values[0].MetricID = "other"
			case "duplicate":
				batch.Values = append(batch.Values, batch.Values[0])
			case "null":
				batch.Values[0].Value = nil
			case "source":
				batch.SourceIdentity = "account-two"
			case "package":
				batch.PackageSHA256 = strings.Repeat("f", 64)
			case "evidence":
				batch.Evidence[0].SHA256 = strings.Repeat("f", 64)
			case "path":
				batch.Evidence[0].Path = "../outside.json"
			case "future":
				batch.CapturedAt = "2026-11-04T16:20:00Z"
			case "window":
				batch.WindowStart = "2026-11-02T15:59:59Z"
			case "date":
				batch.Date = "2026-11-02"
			case "script":
				if err := os.WriteFile(filepath.Join(project, ".roami/okr/connectors/source/scripts/fetch.py"), []byte("changed\n"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := s.RecordConnectorBatch("project", before.Revision, batch); err == nil {
				t.Fatal("invalid batch accepted")
			}
			actual, err := os.ReadFile(pointer)
			if err != nil || string(actual) != string(original) {
				t.Fatal("failed batch moved confirmed pointer", err)
			}
			current, err := s.Get("project")
			if err != nil || len(current.Observations) != len(before.Observations) || len(current.ConnectorBatches) != 0 {
				t.Fatal("failure changed facts", current, err)
			}
		})
	}
}

func TestConnectorBindingCodeChangesRequireConfirmationAndLegacyClientsPreserveBinding(t *testing.T) {
	s, project, before, batch := connectorFixture(t, false)
	config := before.Config
	config.Connectors = nil
	config.Objective = "Keep this workflow"
	kept, err := s.Save("project", config)
	if err != nil || len(kept.Connectors) != 1 {
		t.Fatal(kept, err)
	}
	if _, err := s.Observe("project", kept.Revision, "users", "2026-11-03", 5, "bypass"); !errors.Is(err, ErrInvalid) {
		t.Fatal("bound metric bypassed evidence", err)
	}
	file := filepath.Join(project, ".roami/okr/connectors/source/scripts/fetch.py")
	if err := os.WriteFile(file, []byte("print('new candidate')\n"), 0600); err != nil {
		t.Fatal(err)
	}
	current, err := s.Get("project")
	if err != nil || !current.ProjectFiles.PendingChanges {
		t.Fatal("unconfirmed code not visible", current, err)
	}
	if _, err := s.RecordConnectorBatch("project", kept.Revision, batch); !errors.Is(err, ErrPending) {
		t.Fatal("unconfirmed code was published", err)
	}
	synced, err := s.Sync("project", kept.Revision)
	if err != nil || synced.ProjectFiles.PendingChanges || synced.Connectors[0].PackageSHA256 == before.Connectors[0].PackageSHA256 {
		t.Fatal("code not reconfirmed", synced, err)
	}
	batch.PackageSHA256 = synced.Connectors[0].PackageSHA256
	if _, err := s.RecordConnectorBatch("project", synced.Revision, batch); err != nil {
		t.Fatal(err)
	}
}

func TestGitHubSkillBatchRequiresRepositoryIdentityAndExactRawCounts(t *testing.T) {
	s, project, before, batch := connectorFixture(t, true)
	wrong := 9.0
	batch.Values[0].Value = &wrong
	if _, err := s.RecordConnectorBatch("project", before.Revision, batch); !errors.Is(err, ErrInvalid) {
		t.Fatal("invented GitHub count accepted", err)
	}
	zero := 0.0
	batch.Values[0].Value = &zero
	body := []byte(`{"id":43,"full_name":"owner/project","private":false,"stargazers_count":0,"forks_count":3}`)
	if err := os.WriteFile(filepath.Join(project, batch.Evidence[0].Path), body, 0600); err != nil {
		t.Fatal(err)
	}
	batch.Evidence[0].SHA256 = hashText(body)
	if _, err := s.RecordConnectorBatch("project", before.Revision, batch); !errors.Is(err, ErrInvalid) {
		t.Fatal("repository replacement accepted", err)
	}
	collector := GitHub{Client: &http.Client{Transport: roundTrip(func(*http.Request) (*http.Response, error) { return githubResponse(200, string(body)), nil })}}
	if _, err := s.Collect(context.Background(), collector, "project", before.Revision, false); !errors.Is(err, ErrSource) {
		t.Fatal("builtin fallback replaced confirmed source identity", err)
	}
	current, _ := s.Get("project")
	if current.Revision != before.Revision {
		t.Fatal("failure wrote new revision")
	}
}

func TestConnectorPackageAndEvidenceRejectSymlinks(t *testing.T) {
	s, project, before, batch := connectorFixture(t, false)
	file := filepath.Join(project, batch.Evidence[0].Path)
	if err := os.Remove(file); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(t.TempDir(), "source.json")
	if err := os.WriteFile(outside, []byte(`{}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, file); err != nil {
		t.Fatal(err)
	}
	if _, err := s.RecordConnectorBatch("project", before.Revision, batch); err == nil {
		t.Fatal("evidence symlink accepted")
	}
	cfg := before.Config
	cfg.Connectors[0].Files = append(cfg.Connectors[0].Files, "../outside.py")
	if _, err := s.Save("project", cfg); !errors.Is(err, ErrInvalid) {
		t.Fatal("package escaped root", err)
	}
}

func TestConnectorBatchReceiptExportIsJSON(t *testing.T) {
	s, project, before, batch := connectorFixture(t, true)
	after, err := s.RecordConnectorBatch("project", before.Revision, batch)
	if err != nil {
		t.Fatal(err)
	}
	pointer, err := os.ReadFile(filepath.Join(project, ".roami/okr/state/current.json"))
	if err != nil {
		t.Fatal(err)
	}
	var ref confirmedPointer
	if err := json.Unmarshal(pointer, &ref); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(filepath.Join(project, ".roami/okr", ref.Snapshot))
	if err != nil {
		t.Fatal(err)
	}
	var snapshot confirmedSnapshot
	if err := json.Unmarshal(body, &snapshot); err != nil || snapshot.Workspace.ConnectorBatches[0].ID != batch.ID || snapshot.Workspace.Revision != after.Revision {
		t.Fatal("receipt not in authoritative snapshot", err)
	}
}

func TestGitHubPreparedSkillBatchPublishesExactCandidate(t *testing.T) {
	s, project, before, _ := connectorFixture(t, true)
	script, err := os.ReadFile("../../skills/okr-development/parts/connectors/github/scripts/prepare_batch.py")
	if err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(project, ".roami/okr/connectors/source/scripts/prepare_batch.py")
	if err := os.WriteFile(file, script, 0600); err != nil {
		t.Fatal(err)
	}
	c := before.Config
	c.Connectors[0].Files = append(c.Connectors[0].Files, "scripts/prepare_batch.py")
	c.Connectors[0].PackageSHA256 = ""
	current, err := s.Save("project", c)
	if err != nil {
		t.Fatal(err)
	}
	workspace, _ := json.Marshal(map[string]any{"data": current})
	if err := os.WriteFile(filepath.Join(project, "workspace.json"), workspace, 0600); err != nil {
		t.Fatal(err)
	}
	raw := []byte(`{"id":42,"full_name":"owner/project","private":false,"stargazers_count":0,"forks_count":3}`)
	var payload any
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatal(err)
	}
	candidate, _ := json.Marshal(map[string]any{"schemaVersion": 1, "candidateOnly": true, "source": map[string]any{"service": "github", "repo": "owner/project", "repositoryId": 42}, "asOf": "2026-11-03", "capturedAt": "2026-11-02T16:20:00Z", "values": map[string]any{"stars": 0, "forks": 3}, "evidence": map[string]any{"sha256": hashText(raw), "payload": payload, "http": map[string]any{"status": 200, "body": string(raw)}}})
	if err := os.WriteFile(filepath.Join(project, "candidate.json"), candidate, 0600); err != nil {
		t.Fatal(err)
	}
	command := exec.Command("python3", file, "--workspace", filepath.Join(project, "workspace.json"), "--candidate", filepath.Join(project, "candidate.json"), "--connector", "source", "--batch-id", strings.Repeat("b", 32), "--project", project, "--evidence", "delivery/raw.json", "--output", "delivery/request.json")
	if out, err := command.CombinedOutput(); err != nil {
		t.Fatalf("prepare: %s %v", out, err)
	}
	var request struct {
		Revision int64          `json:"revision"`
		Batch    ConnectorBatch `json:"batch"`
	}
	body, err := os.ReadFile(filepath.Join(project, "delivery/request.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(body, &request); err != nil {
		t.Fatal(err)
	}
	after, err := s.RecordConnectorBatch("project", request.Revision, request.Batch)
	if err != nil {
		t.Fatal(err)
	}
	if len(after.Observations) != 1 || after.Observations[0].Value != 0 || after.ConnectorBatches[0].Evidence[0].SHA256 != hashText(raw) {
		t.Fatal("candidate replaced or fetched independently", after)
	}
}
