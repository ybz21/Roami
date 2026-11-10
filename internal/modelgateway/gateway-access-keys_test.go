package modelgateway

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

func manageAccessKeys(t *testing.T, h *Handler, method, path string, fields map[string]any) map[string]any {
	t.Helper()
	if fields == nil {
		fields = map[string]any{}
	}
	if method != "GET" {
		fields["revision"] = h.Catalog.value.Revision
	}
	body, _ := json.Marshal(fields)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(method, "/v1/model-gateway/access-keys"+path, strings.NewReader(string(body))))
	if w.Code != 200 {
		t.Fatalf("%s %s: %d %s", method, path, w.Code, w.Body)
	}
	var result struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	return result.Data
}
func TestGeneratedGatewayKeysAreIndependentAndRevealOnlyOnce(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-completions")
	agent := h.Catalog.credential("opencode")
	first := manageAccessKeys(t, h, "POST", "", map[string]any{"name": "Laptop"})
	secret := first["apiKey"].(string)
	id := first["keys"].([]any)[0].(map[string]any)["id"].(string)
	second := manageAccessKeys(t, h, "POST", "", map[string]any{"name": "Phone"})
	other := second["apiKey"].(string)
	if secret == other || len(secret) < 40 || !strings.HasPrefix(secret, "sk-roami-") {
		t.Fatal("weak or reused key")
	}
	if kind, _ := h.Catalog.authenticate(secret); kind != "external" {
		t.Fatal("generated key did not authenticate")
	}
	oldGeneration := h.Catalog.value.AccessKeys[0].Generation
	renamed := manageAccessKeys(t, h, "PATCH", "/"+id, map[string]any{"name": "Desktop"})
	if renamed["apiKey"] != nil {
		t.Fatal("rename disclosed key")
	}
	manageAccessKeys(t, h, "PATCH", "/"+id, map[string]any{"disabled": true})
	if kind, _ := h.Catalog.authenticate(secret); kind != "" {
		t.Fatal("disabled key authenticated")
	}
	if kind, _ := h.Catalog.authenticate(other); kind != "external" {
		t.Fatal("other key changed")
	}
	manageAccessKeys(t, h, "PATCH", "/"+id, map[string]any{"disabled": false})
	rotated := manageAccessKeys(t, h, "POST", "/"+id+"/rotate", nil)
	replacement := rotated["apiKey"].(string)
	if replacement == secret || h.Catalog.keyAllowed("external", oldGeneration) {
		t.Fatal("rotation retained credential generation")
	}
	if kind, _ := h.Catalog.authenticate(secret); kind != "" {
		t.Fatal("old key authenticated")
	}
	next := h.Catalog.snapshot()
	if err := h.Catalog.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	reloaded, err := openCatalog(h.Ledger)
	if err != nil {
		t.Fatal(err)
	}
	h.Catalog = reloaded
	if kind, _ := h.Catalog.authenticate(replacement); kind != "external" {
		t.Fatal("catalog reload lost key")
	}
	view := manageAccessKeys(t, h, "GET", "", nil)
	if view["apiKey"] != nil {
		t.Fatal("GET disclosed key")
	}
	var stored string
	_ = h.Ledger.db.QueryRow(`SELECT value FROM gateway_catalog WHERE id=1`).Scan(&stored)
	for _, key := range []string{secret, other, replacement} {
		if strings.Contains(stored, key) {
			t.Fatal("plaintext key persisted")
		}
	}
	manageAccessKeys(t, h, "DELETE", "/"+id, nil)
	if kind, _ := h.Catalog.authenticate(replacement); kind != "" {
		t.Fatal("deleted key authenticated")
	}
	if kind, _ := h.Catalog.authenticate(other); kind != "external" {
		t.Fatal("deleting key changed other client")
	}
	if h.Catalog.credential("opencode") != agent {
		t.Fatal("internal agent credential changed")
	}
}
func TestManagedGatewayKeysPreserveAndManageLegacyKey(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-completions")
	if w := setAccessKey(t, h, "PUT", "fixture-existing-client-key", h.Catalog.value.Revision); w.Code != 200 {
		t.Fatal(w.Body)
	}
	id := h.Catalog.value.AccessKey.ID
	manageAccessKeys(t, h, "POST", "", map[string]any{"name": "New client"})
	view := manageAccessKeys(t, h, "GET", "", nil)
	if len(view["keys"].([]any)) != 2 {
		t.Fatal("legacy key hidden")
	}
	manageAccessKeys(t, h, "PATCH", "/"+id, map[string]any{"name": "Existing client", "disabled": true})
	if kind, _ := h.Catalog.authenticate("fixture-existing-client-key"); kind != "" {
		t.Fatal("legacy key remained enabled")
	}
	manageAccessKeys(t, h, "DELETE", "/"+id, nil)
	if h.Catalog.value.AccessKey.Hash != "" || len(h.Catalog.value.AccessKeys) != 1 {
		t.Fatal("legacy deletion affected managed keys")
	}
}
