package modelgateway

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCatalogCredentialChangeInvalidatesVerificationWithUnchangedAlias(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-responses")
	s := h.Catalog
	path := filepath.Join(s.ledger.paths.Data, "agents", "model-catalog-revision")
	before, err := os.ReadFile(path)
	if err != nil || strings.Contains(string(before), "upstream-secret") {
		t.Fatal("verification fingerprints missing or exposing credentials", err)
	}
	next := s.view(context.Background())
	next.Sources[0].APIKey = "test-next"
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(path)
	if err != nil || string(after) == string(before) {
		t.Fatal("source credentials changed without invalidating verification", err)
	}
	if s.value.Models[0].ID != "coding-main" {
		t.Fatal("test must keep the gateway model alias unchanged")
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("catalog verification marker must be private", err)
	}
}

func TestUnrelatedCatalogChangesPreserveExistingRouteVerification(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-responses")
	s := h.Catalog
	path := filepath.Join(s.ledger.paths.Data, "agents", "model-catalog-revision")
	read := func() map[string]string {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		var value map[string]string
		if err := json.Unmarshal(raw, &value); err != nil {
			t.Fatal(err)
		}
		return value
	}
	before := read()["coding-main"]
	next := s.view(context.Background())
	next.Sources = append(next.Sources, ModelSource{ID: "other", Name: "Other", BaseURL: "https://other.example/v1", Protocol: "openai-responses", AuthMode: "bearer", APIKey: "test-other"})
	next.Models = append(next.Models, CatalogModel{ID: "other-model", Name: "Other", Protocol: "openai-responses", Strategy: "fixed", Candidates: []ModelCandidate{{"other", "other-upstream"}}})
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	after := read()
	if after["coding-main"] != before || after["other-model"] == "" {
		t.Fatal("adding an unrelated route invalidated a verified model")
	}
}
