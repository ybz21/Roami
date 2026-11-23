package modelgateway

import (
	"context"
	"testing"
)

func TestModelSourceKeyIsStoredAndUnique(t *testing.T) {
	h := catalogHandler(t, "https://models.example/v1", "openai-completions")
	ctx := context.Background()
	next := h.Catalog.view(ctx)
	typedKey := " bladeai "
	next.Sources[0].SourceKey = &typedKey
	if err := h.Catalog.update(ctx, next); err != nil {
		t.Fatal(err)
	}
	reopened, err := openCatalog(h.Ledger)
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
	second.ID = "bladeai"
	second.SourceKey = nil
	next.Sources = append(next.Sources, second)
	if err := reopened.update(ctx, next); err == nil || err.Error() != "MODEL_SOURCE_KEY_IN_USE" {
		t.Fatalf("duplicate source key: %v", err)
	}
	next = reopened.view(ctx)
	typedKey = "invalid/key"
	next.Sources[0].SourceKey = &typedKey
	if err := reopened.update(ctx, next); err == nil || err.Error() != "INVALID_MODEL_SOURCE_KEY" {
		t.Fatalf("invalid source key: %v", err)
	}
	next = reopened.view(ctx)
	typedKey = ""
	next.Sources[0].SourceKey = &typedKey
	if err := reopened.update(ctx, next); err != nil {
		t.Fatal(err)
	}
	if reopened.view(ctx).Sources[0].SourceKey != nil {
		t.Fatal("empty key did not reset the source key")
	}
}
