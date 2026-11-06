package api

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/backend/okr"
)

func TestProjectOKRRecordSupportsConfirmedSkillBatchAndExactRetry(t *testing.T) {
	a, router, id := projectOKRFixture(t)
	initial := projectOKRRequest(t, router, "PUT", "/projects/"+id+"/okr", projectOKRConfigJSON(), 200)
	var response struct {
		Data okr.Workspace `json:"data"`
	}
	if err := json.Unmarshal(initial.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	entry, _ := a.Projects.Entry(id)
	pkg := filepath.Join(entry.Dir, ".roami/okr/connectors/source")
	if err := os.MkdirAll(pkg, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(pkg, "SKILL.md"), []byte("---\nname: source\ndescription: Read scoped observations.\n---\nUse authorized source tools.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	c := response.Data.Config
	c.Connectors = []okr.SkillConnector{{ID: "source", Name: "Source", Service: "mcp", Identity: "account-one", Timezone: "UTC", Window: "snapshot", Files: []string{"SKILL.md"}, Bindings: []okr.ConnectorMetric{{MetricID: "users", Field: "users"}}}}
	body, _ := json.Marshal(c)
	saved := projectOKRRequest(t, router, "PUT", "/projects/"+id+"/okr", string(body), 200)
	if err := json.Unmarshal(saved.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	raw := []byte(`{"account":"account-one","users":0}`)
	sum := sha256.Sum256(raw)
	if err := os.WriteFile(filepath.Join(entry.Dir, "source.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	unit, zero := "people", 0.0
	captured := time.Now().UTC().Add(-time.Second).Format(time.RFC3339Nano)
	batch := okr.ConnectorBatch{ID: strings.Repeat("a", 32), ConnectorID: "source", PackageSHA256: response.Data.Connectors[0].PackageSHA256, SourceIdentity: "account-one", Date: captured[:10], CapturedAt: captured, WindowStart: captured, WindowEnd: captured, Values: []okr.ConnectorBatchValue{{MetricID: "users", Unit: &unit, Value: &zero}}, Evidence: []okr.ConnectorBatchEvidence{{Path: "source.json", SHA256: hex.EncodeToString(sum[:])}}}
	payload := map[string]any{"revision": response.Data.Revision, "batch": batch}
	body, _ = json.Marshal(payload)
	first := projectOKRRequest(t, router, "POST", "/projects/"+id+"/okr/observations", string(body), 200)
	second := projectOKRRequest(t, router, "POST", "/projects/"+id+"/okr/observations", string(body), 200)
	if first.Body.String() != second.Body.String() {
		t.Fatal("same request changed the confirmed workspace")
	}
	payload["metricId"] = "users"
	body, _ = json.Marshal(payload)
	projectOKRRequest(t, router, "POST", "/projects/"+id+"/okr/observations", string(body), 400)
	delete(payload, "metricId")
	batch.Note = "Changed request"
	payload["batch"] = batch
	body, _ = json.Marshal(payload)
	projectOKRRequest(t, router, "POST", "/projects/"+id+"/okr/observations", string(body), 409)
}
