package service

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestModelSourceKeyIsStoredAndUnique(t *testing.T) {
	h := catalogHandler(t, "https://models.example/v1", "openai-completions")
	ctx := context.Background()
	next := h.Catalog.view(ctx)
	typedKey := "bladeai"
	next.Sources[0].SourceKey = &typedKey
	if err := h.Catalog.update(ctx, next); err != nil {
		t.Fatal(err)
	}
	reopened, err := openCatalog(h.state)
	if err != nil {
		t.Fatal(err)
	}
	next = reopened.view(ctx)
	if key := next.Sources[0].SourceKey; key == nil || *key != "bladeai" {
		t.Fatal("model source key was not persisted")
	}
	next.Sources[0].SourceKey = nil
	if err := reopened.update(ctx, next); err != nil {
		t.Fatal(err)
	}
	next = reopened.view(ctx)
	if key := next.Sources[0].SourceKey; key == nil || *key != "bladeai" {
		t.Fatal("an omitted key overwrote the saved key")
	}
	second := next.Sources[0]
	second.ID = "second"
	next.Sources = append(next.Sources, second)
	if err := reopened.update(ctx, next); err == nil || err.Error() != "MODEL_SOURCE_KEY_IN_USE" {
		t.Fatalf("duplicate source key: %v", err)
	}
	next = reopened.view(ctx)
	for _, key := range []string{"invalid/key", "blade.ai", "blade_ai", " bladeai ", "模型", strings.Repeat("a", 161)} {
		next.Sources[0].SourceKey = &key
		if err := reopened.update(ctx, next); err == nil || err.Error() != "INVALID_MODEL_SOURCE_KEY" {
			t.Fatalf("invalid source key %q: %v", key, err)
		}
	}
	next = reopened.view(ctx)
	typedKey = ""
	next.Sources[0].SourceKey = &typedKey
	if err := reopened.update(ctx, next); err == nil || err.Error() != "MODEL_SOURCE_KEY_REQUIRED" {
		t.Fatalf("empty source key: %v", err)
	}
}

func TestCatalogRequiresKeyForNewSource(t *testing.T) {
	h := catalogHandler(t, "https://models.example/v1", "openai-completions")
	next := h.Catalog.view(context.Background())
	next.Sources = append(next.Sources, ModelSource{
		ID: "second", Name: "Second", BaseURL: "https://other.example/v1",
		Protocol: "openai-completions", AuthMode: "bearer",
	})
	save := func() *httptest.ResponseRecorder {
		t.Helper()
		body, err := json.Marshal(next)
		if err != nil {
			t.Fatal(err)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodPut, "/v1/model-gateway/catalog", bytes.NewReader(body)))
		return w
	}
	if w := save(); w.Code != http.StatusBadRequest || !strings.Contains(w.Body.String(), "MODEL_SOURCE_KEY_REQUIRED") {
		t.Fatalf("missing key: %d %s", w.Code, w.Body)
	}
	key := "Blade-01"
	next.Sources[1].SourceKey = &key
	if w := save(); w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"sourceKey":"Blade-01"`) {
		t.Fatalf("valid key: %d %s", w.Code, w.Body)
	}
}

func TestCatalogMigratesLegacySourceKeys(t *testing.T) {
	h := catalogHandler(t, "https://models.example/v1", "openai-completions")
	next := h.Catalog.snapshot()
	oldKey, validKey := "blade.ai", "blade-ai"
	next.Sources[0].SourceKey = &oldKey
	next.Sources = append(next.Sources,
		ModelSource{ID: "explicit", SourceKey: &validKey},
		ModelSource{ID: "blade_ai"},
	)
	if err := h.Catalog.persist(next); err != nil {
		t.Fatal(err)
	}
	expected := []string{"blade-ai-2", "blade-ai", "blade-ai-3"}
	for range 2 {
		reopened, err := openCatalog(h.state)
		if err != nil {
			t.Fatal(err)
		}
		saved := reopened.snapshot()
		for i, source := range saved.Sources {
			if source.SourceKey == nil || *source.SourceKey != expected[i] {
				t.Fatalf("source %s did not get key %s", source.ID, expected[i])
			}
		}
		if saved.Models[0].Candidates[0] != next.Models[0].Candidates[0] || saved.Sources[0].APIKey != next.Sources[0].APIKey {
			t.Fatal("migration changed a route or credential")
		}
	}
}
