package okr

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type GitHub struct{ Client *http.Client }

type repositoryCounts struct {
	ID           int64
	Stars, Forks float64
}

func (g GitHub) fetch(ctx context.Context, repo string) (repositoryCounts, error) {
	if !repository.MatchString(repo) {
		return repositoryCounts{}, ErrInvalid
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://api.github.com/repos/"+repo, nil)
	if err != nil {
		return repositoryCounts{}, ErrSource
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", "Roami-project-okr")
	client := http.Client{Timeout: 15 * time.Second}
	if g.Client != nil {
		client = *g.Client
	}
	// Redirects must not turn a confirmed public source into another endpoint.
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	resp, err := client.Do(req)
	if err != nil {
		return repositoryCounts{}, fmt.Errorf("%w: request", ErrSource)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return repositoryCounts{}, fmt.Errorf("%w: HTTP %d", ErrSource, resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if err != nil {
		return repositoryCounts{}, ErrSource
	}
	var payload struct {
		ID       *int64 `json:"id"`
		FullName string `json:"full_name"`
		Private  *bool  `json:"private"`
		Stars    *int64 `json:"stargazers_count"`
		Forks    *int64 `json:"forks_count"`
	}
	const maxSafeInteger = 1<<53 - 1
	if json.Unmarshal(body, &payload) != nil || payload.ID == nil || *payload.ID <= 0 || !strings.EqualFold(payload.FullName, repo) || payload.Private == nil || *payload.Private || payload.Stars == nil || *payload.Stars < 0 || *payload.Stars > maxSafeInteger || payload.Forks == nil || *payload.Forks < 0 || *payload.Forks > maxSafeInteger {
		return repositoryCounts{}, ErrSource
	}
	return repositoryCounts{ID: *payload.ID, Stars: float64(*payload.Stars), Forks: float64(*payload.Forks)}, nil
}

func sourceKey(repoID int64, field string) string {
	return "github:" + strconv.FormatInt(repoID, 10) + ":" + field
}
