package agentproviders

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"time"
)

type ModelQuery struct {
	ProfileInput
	ProfileID string `json:"profileId"`
}

func (s *Store) ModelOptions(ctx context.Context, kind string, query ModelQuery) ([]string, error) {
	if err := validateKind(kind); err != nil {
		return nil, err
	}
	var profile Profile
	err := s.locked(func(state *catalog) error {
		var previous *Profile
		if query.ProfileID != "" {
			for _, p := range stateFor(state, kind).Profiles {
				if p.ID == query.ProfileID {
					copy := p
					previous = &copy
					break
				}
			}
			if previous == nil {
				return fmt.Errorf("MODEL_PROFILE_NOT_FOUND")
			}
		}
		// Discovery needs the connection, independently of unfinished identity fields.
		input := query.ProfileInput
		input.Name, input.Model, input.ReasoningEffort = "Model list", "model-list", ""
		var err error
		profile, err = profileFromInput(kind, query.ProfileID, input, previous)
		return err
	})
	if err != nil {
		return nil, err
	}
	if profile.KeyEnv != "" {
		profile.APIKey = os.Getenv(profile.KeyEnv)
		if profile.APIKey == "" || strings.ContainsAny(profile.APIKey, "\r\n\x00") {
			return nil, fmt.Errorf("MODEL_KEY_ENV_MISSING")
		}
	}
	return ReadSourceModels(ctx, profile)
}

// ReadSourceModels lists models from an already validated source.
func ReadSourceModels(ctx context.Context, profile Profile) ([]string, error) {
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	endpoint, err := url.Parse(profile.BaseURL)
	if err != nil {
		return nil, fmt.Errorf("INVALID_MODEL_PROFILE")
	}
	anthropic := profile.Protocol == "anthropic-messages"
	if anthropic && !strings.HasSuffix(strings.TrimRight(endpoint.Path, "/"), "/v1") {
		endpoint = endpoint.JoinPath("v1", "models")
	} else {
		endpoint = endpoint.JoinPath("models")
	}
	client := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	models := map[string]bool{}
	cursors := map[string]bool{}
	remaining := int64(maxFileSize)
	for page := 0; page < 10; page++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
		if err != nil {
			return nil, fmt.Errorf("MODEL_LIST_FAILED")
		}
		if anthropic {
			req.Header.Set("anthropic-version", "2023-06-01")
			if profile.AuthMode == "bearer" {
				req.Header.Set("Authorization", "Bearer "+profile.APIKey)
			} else {
				req.Header.Set("x-api-key", profile.APIKey)
			}
		} else {
			req.Header.Set("Authorization", "Bearer "+profile.APIKey)
		}
		req.Header.Set("Accept", "application/json")
		response, err := client.Do(req)
		if err != nil {
			return nil, fmt.Errorf("MODEL_LIST_FAILED")
		}
		body, readErr := io.ReadAll(io.LimitReader(response.Body, remaining+1))
		_ = response.Body.Close()
		if response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden {
			return nil, fmt.Errorf("MODEL_LIST_UNAUTHORIZED")
		}
		if response.StatusCode == http.StatusNotFound || response.StatusCode == http.StatusMethodNotAllowed {
			return nil, fmt.Errorf("MODEL_LIST_UNSUPPORTED")
		}
		if response.StatusCode != http.StatusOK || readErr != nil || int64(len(body)) > remaining {
			return nil, fmt.Errorf("MODEL_LIST_FAILED")
		}
		remaining -= int64(len(body))
		var result struct {
			Data []struct {
				ID string `json:"id"`
			} `json:"data"`
			HasMore bool   `json:"has_more"`
			LastID  string `json:"last_id"`
		}
		if json.Unmarshal(body, &result) != nil || result.Data == nil || len(result.Data) > 1000 {
			return nil, fmt.Errorf("MODEL_LIST_FAILED")
		}
		for _, item := range result.Data {
			id := strings.TrimSpace(item.ID)
			if id != "" && len(id) <= 256 && !strings.ContainsAny(id, "\r\n\x00") && !strings.Contains(id, "{env:") && !strings.Contains(id, "{file:") && id != profile.APIKey {
				models[id] = true
			}
		}
		if len(models) > 1000 {
			return nil, fmt.Errorf("MODEL_LIST_FAILED")
		}
		if !result.HasMore {
			ids := make([]string, 0, len(models))
			for id := range models {
				ids = append(ids, id)
			}
			sort.Strings(ids)
			return ids, nil
		}
		if !anthropic || result.LastID == "" || len(result.LastID) > 256 || cursors[result.LastID] {
			return nil, fmt.Errorf("MODEL_LIST_FAILED")
		}
		cursors[result.LastID] = true
		params := endpoint.Query()
		params.Set("after_id", result.LastID)
		endpoint.RawQuery = params.Encode()
	}
	return nil, fmt.Errorf("MODEL_LIST_FAILED")
}
