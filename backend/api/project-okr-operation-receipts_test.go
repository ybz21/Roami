package api

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestProjectOKRStableOperationKeysReturnOriginalEffects(t *testing.T) {
	a, router, id := projectOKRFixture(t)
	endpoint := "/projects/" + id + "/okr"
	w := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint, projectOKRConfigJSON(), 200))
	if !w.ProjectFiles.OperationReceiptsSupported {
		t.Fatal("receipt capability not advertised")
	}
	request := func(method, suffix string, body any, status int) string {
		encoded, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		return projectOKRRequest(t, router, method, endpoint+suffix, string(encoded), status).Body.String()
	}
	observe := map[string]any{"operationKey": "cycle:observation", "revision": w.Revision, "metricId": "users", "date": "2001-01-01", "value": 0, "note": "Actual measured zero"}
	encoded, _ := json.Marshal(observe)
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", endpoint+"/observations", string(encoded), 200))
	receipt := w.ProjectFiles.OperationReceipt
	observe["revision"] = w.Revision
	encoded, _ = json.Marshal(observe)
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", endpoint+"/observations", string(encoded), 200))
	if len(w.Observations) != 1 || w.Observations[0].Value != 0 || !reflect.DeepEqual(receipt, w.ProjectFiles.OperationReceipt) {
		t.Fatal(w)
	}
	observe["value"] = 1
	request("POST", "/observations", observe, 409)
	review := map[string]any{"operationKey": "cycle:review", "revision": w.Revision, "summary": "Checked source and result", "actions": "Continue original roles"}
	encoded, _ = json.Marshal(review)
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", endpoint+"/reviews", string(encoded), 200))
	receipt = w.ProjectFiles.OperationReceipt
	review["revision"] = w.Revision
	encoded, _ = json.Marshal(review)
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", endpoint+"/reviews", string(encoded), 200))
	originalReviewID := w.Reviews[0].ID
	if len(w.Reviews) != 1 || !reflect.DeepEqual(receipt, w.ProjectFiles.OperationReceipt) {
		t.Fatal(w.Reviews)
	}
	memory := map[string]any{"operationKey": "cycle:memory", "mode": "append", "content": "Verified dated note", "expectedSha256": w.ProjectFiles.TeamMemorySha256}
	encoded, _ = json.Marshal(memory)
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint+"/memory", string(encoded), 200))
	receipt = w.ProjectFiles.OperationReceipt
	content := w.ProjectFiles.TeamMemory
	memory["expectedSha256"] = w.ProjectFiles.TeamMemorySha256
	encoded, _ = json.Marshal(memory)
	w = decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", endpoint+"/memory", string(encoded), 200))
	if w.ProjectFiles.TeamMemory != content || !reflect.DeepEqual(receipt, w.ProjectFiles.OperationReceipt) {
		t.Fatal(w.ProjectFiles)
	}
	memory["mode"] = "replace"
	request("PUT", "/memory", memory, 400)
	memory["mode"] = "append"
	memory["operationKey"] = "cycle:review"
	request("PUT", "/memory", memory, 409)
	memory["operationKey"] = ""
	request("PUT", "/memory", memory, 400)
	observe["operationKey"] = ""
	request("POST", "/observations", observe, 400)
	current := decodeProjectOKR(t, projectOKRRequest(t, router, "GET", endpoint, "", 200))
	if current.ProjectFiles.OperationReceipt != nil || len(current.Reviews) != 1 || len(current.Observations) != 1 || current.ProjectFiles.TeamMemory != content {
		t.Fatal("transient receipt polluted confirmed snapshot or a failed request changed data")
	}
	other, added := a.Projects.Add(t.TempDir(), "Independent OKR")
	if !added {
		t.Fatal("independent project was not added")
	}
	otherEndpoint := "/projects/" + other + "/okr"
	otherWorkspace := decodeProjectOKR(t, projectOKRRequest(t, router, "PUT", otherEndpoint, projectOKRConfigJSON(), 200))
	review["revision"] = otherWorkspace.Revision
	encoded, _ = json.Marshal(review)
	otherWorkspace = decodeProjectOKR(t, projectOKRRequest(t, router, "POST", otherEndpoint+"/reviews", string(encoded), 200))
	if len(otherWorkspace.Reviews) != 1 || otherWorkspace.Reviews[0].ID == originalReviewID {
		t.Fatal("a shared operation key crossed the project boundary")
	}

}
