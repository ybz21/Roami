package agentproviders

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
)

func TestModelOptionsUsesPrivateKeyWithoutSavingDraft(t *testing.T) {
	for _, kind := range []string{"claude", "codex", "opencode", "pi"} {
		t.Run(kind, func(t *testing.T) {
			store, _ := isolatedProviderStore(t)
			input := modelInput(kind)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				expected := "/gateway/models"
				if kind == "claude" {
					expected = "/gateway/v1/models"
				}
				if r.Method != "GET" || r.URL.Path != expected {
					t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
				}
				if kind == "claude" {
					if r.Header.Get("x-api-key") != *input.APIKey || r.Header.Get("anthropic-version") == "" {
						t.Error("missing Anthropic credentials")
					}
				} else if r.Header.Get("Authorization") != "Bearer "+*input.APIKey {
					t.Error("missing bearer credentials")
				}
				_, _ = fmt.Fprint(w, `{"data":[{"id":"z-model"},{"id":"a-model"},{"id":"z-model"}],"apiKey":"not-returned"}`)
			}))
			defer server.Close()
			input.BaseURL = server.URL + "/gateway"
			p, err := store.Save(context.Background(), kind, "", input)
			if err != nil {
				t.Fatal(err)
			}
			draft := input
			draft.Name, draft.Model, draft.APIKey = "", "", nil
			models, err := store.ModelOptions(context.Background(), kind, ModelQuery{ProfileInput: draft, ProfileID: p.ID})
			if err != nil || !reflect.DeepEqual(models, []string{"a-model", "z-model"}) {
				t.Fatalf("models: %v %v", models, err)
			}
			view, err := store.View(context.Background(), kind)
			if err != nil || view.Profiles[0].Applied || view.Profiles[0].Model != input.Model {
				t.Fatal("discovery mutated a preset or native settings")
			}
		})
	}
}

func TestModelOptionsAnthropicPaginationAndEnvironment(t *testing.T) {
	store, _ := isolatedProviderStore(t)
	t.Setenv("FIXTURE_LIST_KEY", "fixture-env-key")
	pages := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		pages++
		if r.URL.Path != "/v1/models" || r.Header.Get("Authorization") != "Bearer fixture-env-key" || r.Header.Get("x-api-key") != "" {
			t.Error("wrong endpoint or authentication")
		}
		if r.URL.Query().Get("after_id") == "" {
			_, _ = fmt.Fprint(w, `{"data":[{"id":"first"}],"has_more":true,"last_id":"first"}`)
		} else {
			_, _ = fmt.Fprint(w, `{"data":[{"id":"second"}],"has_more":false}`)
		}
	}))
	defer server.Close()
	input := modelInput("claude")
	input.BaseURL = server.URL + "/v1/"
	input.APIKey = nil
	input.KeyEnv = "FIXTURE_LIST_KEY"
	input.AuthMode = "bearer"
	models, err := store.ModelOptions(context.Background(), "claude", ModelQuery{ProfileInput: input})
	if err != nil || pages != 2 || len(models) != 2 {
		t.Fatalf("pagination: %v %v (%d pages)", models, err, pages)
	}
}

func TestModelOptionsFailureDoesNotLeakCredentialsOrFollowRedirects(t *testing.T) {
	store, _ := isolatedProviderStore(t)
	for _, status := range []int{401, 404, 302, 500, 200} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			requests := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests++
				w.Header().Set("Location", "/redirect-target")
				w.WriteHeader(status)
				_, _ = fmt.Fprint(w, `{"error":"fixture-provider-credential"}`)
			}))
			defer server.Close()
			input := modelInput("codex")
			input.BaseURL = server.URL
			models, err := store.ModelOptions(context.Background(), "codex", ModelQuery{ProfileInput: input})
			if err == nil || len(models) != 0 || requests != 1 || strings.Contains(err.Error(), *input.APIKey) {
				t.Fatalf("unsafe error: %v %v (%d requests)", models, err, requests)
			}
		})
	}
	input := modelInput("pi")
	input.KeyEnv = "UNSET_FIXTURE_MODEL_KEY"
	input.APIKey = nil
	t.Setenv(input.KeyEnv, "")
	if _, err := store.ModelOptions(context.Background(), "pi", ModelQuery{ProfileInput: input}); err == nil || err.Error() != "MODEL_KEY_ENV_MISSING" {
		t.Fatalf("missing env: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := store.ModelOptions(ctx, "codex", ModelQuery{ProfileInput: modelInput("codex")}); err == nil {
		t.Fatal("cancelled query succeeded")
	}
}

func TestModelOptionsRejectsOversizedOrLoopingLists(t *testing.T) {
	for name, body := range map[string]string{
		"oversized":       `{"data":[],"padding":"` + strings.Repeat("x", maxFileSize) + `"}`,
		"repeated-cursor": `{"data":[{"id":"same"}],"has_more":true,"last_id":"same"}`,
		"missing-data":    `{}`,
	} {
		t.Run(name, func(t *testing.T) {
			store, _ := isolatedProviderStore(t)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = fmt.Fprint(w, body) }))
			defer server.Close()
			input := modelInput("claude")
			input.BaseURL = server.URL
			if models, err := store.ModelOptions(context.Background(), "claude", ModelQuery{ProfileInput: input}); err == nil || err.Error() != "MODEL_LIST_FAILED" || len(models) != 0 {
				t.Fatalf("unbounded list: %v %v", models, err)
			}
		})
	}
}
