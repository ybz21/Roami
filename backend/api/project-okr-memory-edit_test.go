package api

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	"github.com/ybz21/Roami/backend/okr"
)

func TestProjectOKRMemoryEditCompactReceiptAndConflicts(t *testing.T) {
	_, router, id := projectOKRFixture(t)
	endpoint := "/projects/" + id + "/okr"
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint, projectOKRConfigJSON(), 200))
	if !w.ProjectFiles.MemoryEditsSupported {
		t.Fatal("edit capability is absent")
	}
	original := "Current: old rule\n" + strings.Repeat("Unrelated verified fact.\n", 1200)
	seed, _ := json.Marshal(map[string]any{"content": original, "expectedSha256": w.ProjectFiles.TeamMemorySha256})
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint+"/memory", string(seed), 200))
	before := w.ProjectFiles.TeamMemorySha256
	edit := map[string]any{"mode": "edit", "operationKey": "current-rule", "expectedSha256": before,
		"edits": []okr.MemoryEdit{{OldText: "Current: old rule", NewText: "Current: corrected rule"}}}
	encode := func(value any) string {
		t.Helper()
		body, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		return string(body)
	}
	response := projectOKRRequest(t, router, "PUT", endpoint+"/memory", encode(edit), 200)
	var result struct {
		Data struct {
			ProjectID    string            `json:"projectId"`
			ProjectFiles *okr.ProjectFiles `json:"projectFiles"`
		} `json:"data"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	files := result.Data.ProjectFiles
	if result.Data.ProjectID != id || files == nil || files.OperationReceipt == nil || files.OperationReceipt.Kind != "memory_edit" || files.OperationReceipt.PreviousSHA256 != before {
		t.Fatal(response.Body.String())
	}
	if response.Body.Len() > 2000 || strings.Contains(response.Body.String(), `"teamMemory":`) {
		t.Fatal("one edit returned the entire memory or workspace")
	}
	current := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", endpoint, "", 200))
	if current.ProjectFiles.TeamMemory != strings.Replace(original, "old rule", "corrected rule", 1) || current.ProjectFiles.TeamMemorySha256 != files.OperationReceipt.ResultSHA256 {
		t.Fatal("receipt does not describe the edited document")
	}
	appendRequest := map[string]any{"mode": "append", "content": "Later fact", "expectedSha256": current.ProjectFiles.TeamMemorySha256}
	current = decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint+"/memory", encode(appendRequest), 200))
	var replay struct {
		Data struct {
			ProjectFiles *okr.ProjectFiles `json:"projectFiles"`
		} `json:"data"`
	}
	response = projectOKRRequest(t, router, "PUT", endpoint+"/memory", encode(edit), 200)
	if err := json.Unmarshal(response.Body.Bytes(), &replay); err != nil || !reflect.DeepEqual(replay.Data.ProjectFiles.OperationReceipt, files.OperationReceipt) || replay.Data.ProjectFiles.TeamMemorySha256 != current.ProjectFiles.TeamMemorySha256 {
		t.Fatal("replay changed its receipt or discarded newer memory", err)
	}
	edit["operationKey"] = "new-stale-edit"
	projectOKRRequest(t, router, "PUT", endpoint+"/memory", encode(edit), 409)
	edit["expectedSha256"] = current.ProjectFiles.TeamMemorySha256
	edit["content"] = "Mixed replacement"
	projectOKRRequest(t, router, "PUT", endpoint+"/memory", encode(edit), 400)
	delete(edit, "content")
	delete(edit, "operationKey")
	projectOKRRequest(t, router, "PUT", endpoint+"/memory", encode(edit), 400)
	unchanged := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", endpoint, "", 200))
	if unchanged.ProjectFiles.TeamMemory != current.ProjectFiles.TeamMemory {
		t.Fatal("rejected edit modified current memory")
	}
}
