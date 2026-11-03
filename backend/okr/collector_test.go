package okr

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"reflect"
	"strings"
	"testing"
	"time"
)

type roundTrip func(*http.Request) (*http.Response, error)

func (r roundTrip) RoundTrip(req *http.Request) (*http.Response, error) { return r(req) }

func githubResponse(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(body))}
}

func githubConfig() Config {
	c := testConfig()
	c.AutoCollect = true
	c.Metrics[0] = Metric{ID: "users", Name: "Stars", Unit: "stars", Source: "github", Repo: "owner/project", Field: "stars"}
	return c
}

func TestCollectionStableIdentityVersionsAndDailyRestartDeduplication(t *testing.T) {
	s, paths := testStore(t)
	w, err := s.Save("project", githubConfig())
	if err != nil {
		t.Fatal(err)
	}
	if w.Metrics[0].SourceKey != "" || len(w.Observations) != 0 {
		t.Fatal("fabricated initial evidence")
	}
	calls, repoID, value := 0, 42, 20
	g := GitHub{Client: &http.Client{Transport: roundTrip(func(req *http.Request) (*http.Response, error) {
		calls++
		if req.URL.Scheme != "https" || req.URL.Host != "api.github.com" || req.URL.Path != "/repos/owner/project" || req.Header.Get("Authorization") != "" {
			t.Fatalf("unsafe request: %s", req.URL)
		}
		return githubResponse(200, fmt.Sprintf(`{"id":%d,"full_name":"owner/project","private":false,"stargazers_count":%d,"forks_count":3}`, repoID, value)), nil
	})}}
	if err := s.CollectDue(context.Background(), g, nil); err != nil {
		t.Fatal(err)
	}
	w, _ = s.Get("project")
	if len(w.Observations) != 1 || w.Observations[0].Date != "2026-11-03" || w.Metrics[0].SourceKey != "github:42:stars" {
		t.Fatalf("wrong collected evidence: %+v", w)
	}
	if err := s.db.DB.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	s.now = func() time.Time { return time.Date(2026, 11, 2, 16, 30, 0, 0, time.UTC) }
	if err := s.CollectDue(context.Background(), g, nil); err != nil {
		t.Fatal(err)
	}
	if calls != 1 {
		t.Fatalf("repeated daily request after restart: %d", calls)
	}
	value = 18
	w, err = s.Collect(context.Background(), g, "project", w.Revision, false)
	if err != nil || len(w.Observations) != 2 || w.Observations[0].Value != 20 || w.Observations[1].Value != 18 {
		t.Fatalf("manual same-day version: %+v %v", w, err)
	}
	// The same owner/repo can be deleted and recreated with another stable GitHub ID.
	repoID = 99
	w, err = s.Collect(context.Background(), g, "project", w.Revision, false)
	if err != nil || w.Metrics[0].SourceKey != "github:99:stars" || w.Observations[0].SourceKey != "github:42:stars" {
		t.Fatalf("identity not isolated: %+v %v", w, err)
	}
	s.now = func() time.Time { return time.Date(2026, 11, 3, 16, 0, 0, 0, time.UTC) }
	if err := s.CollectDue(context.Background(), g, nil); err != nil {
		t.Fatal(err)
	}
	w, _ = s.Get("project")
	if calls != 4 || len(w.Observations) != 4 || w.Observations[3].Date != "2026-11-04" {
		t.Fatalf("new Shanghai day not collected: %+v calls=%d", w, calls)
	}
	config := w.Config
	config.Metrics[0].Repo = "owner/another"
	config.Metrics[0].SourceKey = "github:injected:stars"
	w, err = s.Save("project", config)
	if err != nil || w.Metrics[0].SourceKey != "" || len(w.Observations) != 4 {
		t.Fatalf("source edit: %+v %v", w, err)
	}
	config = w.Config
	config.Metrics[0].Source = "manual"
	w, err = s.Save("project", config)
	if err != nil || w.Metrics[0].SourceKey != "manual:users" || len(w.Observations) != 4 {
		t.Fatalf("manual rebind: %+v %v", w, err)
	}
}

func TestCollectionFailureIsAtomicAndConcurrentEditDiscardsResponse(t *testing.T) {
	s, _ := testStore(t)
	c := githubConfig()
	c.Metrics = append(c.Metrics, Metric{ID: "forks", Name: "Forks", Source: "github", Repo: "owner/second", Field: "forks"})
	w, err := s.Save("project", c)
	if err != nil {
		t.Fatal(err)
	}
	g := GitHub{Client: &http.Client{Transport: roundTrip(func(req *http.Request) (*http.Response, error) {
		if strings.HasSuffix(req.URL.Path, "second") {
			return githubResponse(429, `{}`), nil
		}
		return githubResponse(200, `{"id":42,"full_name":"owner/project","private":false,"stargazers_count":3,"forks_count":4}`), nil
	})}}
	if _, err := s.Collect(context.Background(), g, "project", w.Revision, false); !errors.Is(err, ErrSource) {
		t.Fatal(err)
	}
	after, _ := s.Get("project")
	if !reflect.DeepEqual(w, after) {
		t.Fatal("failed second source partially saved first source")
	}
	config := w.Config
	config.Metrics = config.Metrics[:1]
	w, err = s.Save("project", config)
	if err != nil {
		t.Fatal(err)
	}
	g.Client.Transport = roundTrip(func(req *http.Request) (*http.Response, error) {
		config := w.Config
		config.Objective = "Concurrent edit"
		if _, err := s.Save("project", config); err != nil {
			t.Fatal(err)
		}
		return githubResponse(200, `{"id":42,"full_name":"owner/project","private":false,"stargazers_count":3,"forks_count":4}`), nil
	})
	if _, err := s.Collect(context.Background(), g, "project", w.Revision, false); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
	after, _ = s.Get("project")
	if after.Objective != "Concurrent edit" || len(after.Observations) != 0 {
		t.Fatal(after)
	}
}

func TestGitHubRejectsRedirectMissingCountsPrivateAndTimeout(t *testing.T) {
	for _, body := range []string{
		`{}`,
		`{"id":42,"full_name":"owner/repo","private":false,"stargazers_count":0}`,
		`{"id":42,"full_name":"owner/repo","private":true,"stargazers_count":0,"forks_count":0}`,
		`{"id":42,"full_name":"owner/repo","private":false,"stargazers_count":null,"forks_count":0}`,
		`{"id":42,"full_name":"owner/repo","private":false,"stargazers_count":-1,"forks_count":0}`,
		`{"id":42,"full_name":"owner/unconfirmed","private":false,"stargazers_count":1,"forks_count":0}`,
		`{"id":42,"full_name":"owner/repo","private":false,"stargazers_count":9007199254740992,"forks_count":0}`,
	} {
		g := GitHub{Client: &http.Client{Transport: roundTrip(func(*http.Request) (*http.Response, error) { return githubResponse(200, body), nil })}}
		if _, err := g.fetch(context.Background(), "owner/repo"); !errors.Is(err, ErrSource) {
			t.Fatalf("accepted %s: %v", body, err)
		}
	}
	calls := 0
	g := GitHub{Client: &http.Client{Transport: roundTrip(func(*http.Request) (*http.Response, error) {
		calls++
		resp := githubResponse(302, `{}`)
		resp.Header.Set("Location", "https://evil.test/secret")
		return resp, nil
	})}}
	if _, err := g.fetch(context.Background(), "owner/repo"); !errors.Is(err, ErrSource) || calls != 1 {
		t.Fatalf("followed redirect: %d %v", calls, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	g.Client.Transport = roundTrip(func(req *http.Request) (*http.Response, error) { return nil, req.Context().Err() })
	if _, err := g.fetch(ctx, "owner/repo"); !errors.Is(err, ErrSource) {
		t.Fatal(err)
	}
}

func TestAutomaticCollectionOnlyEnabledProjectsAndLifecycleCancellation(t *testing.T) {
	s, _ := testStore(t)
	c := githubConfig()
	c.AutoCollect = false
	if _, err := s.Save("disabled", c); err != nil {
		t.Fatal(err)
	}
	c.AutoCollect = true
	if _, err := s.Save("removed", c); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Save("active", c); err != nil {
		t.Fatal(err)
	}
	entered := make(chan struct{})
	g := GitHub{Client: &http.Client{Transport: roundTrip(func(req *http.Request) (*http.Response, error) {
		close(entered)
		<-req.Context().Done()
		return nil, req.Context().Err()
	})}}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		s.RunCollector(ctx, g, func(projectID string) bool { return projectID != "removed" })
		close(done)
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("startup did not collect today")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("collector did not stop")
	}
	for _, name := range []string{"disabled", "removed", "active"} {
		w, err := s.Get(name)
		if err != nil || w.Revision != 1 || len(w.Observations) != 0 {
			t.Fatalf("failed/disabled collection fabricated observations: %+v %v", w, err)
		}
	}
}

func TestAutomaticPartialFailurePersistsSuccessfulSourceOncePerDay(t *testing.T) {
	s, _ := testStore(t)
	c := githubConfig()
	c.Metrics = append(c.Metrics, Metric{ID: "forks", Name: "Forks", Source: "github", Repo: "owner/unavailable", Field: "forks"})
	if _, err := s.Save("project", c); err != nil {
		t.Fatal(err)
	}
	calls := map[string]int{}
	g := GitHub{Client: &http.Client{Transport: roundTrip(func(req *http.Request) (*http.Response, error) {
		calls[req.URL.Path]++
		if strings.HasSuffix(req.URL.Path, "unavailable") {
			return githubResponse(503, `{}`), nil
		}
		return githubResponse(200, `{"id":42,"full_name":"owner/project","private":false,"stargazers_count":8,"forks_count":2}`), nil
	})}}
	for i := 0; i < 2; i++ {
		if err := s.CollectDue(context.Background(), g, nil); (i == 0 && !errors.Is(err, ErrSource)) || (i == 1 && err != nil) {
			t.Fatal(err)
		}
	}
	w, err := s.Get("project")
	if err != nil || w.Revision != 2 || len(w.Observations) != 1 || w.Observations[0].Value != 8 || calls["/repos/owner/project"] != 1 || calls["/repos/owner/unavailable"] != 1 {
		t.Fatalf("partial daily collection: %+v calls=%v err=%v", w, calls, err)
	}
	if w.Metrics[1].SourceKey != "" {
		t.Fatal("failed source acquired a fabricated identity")
	}
	clock := s.now()
	s.now = func() time.Time { return clock.Add(5 * time.Minute) }
	if err := s.CollectDue(context.Background(), g, nil); !errors.Is(err, ErrSource) {
		t.Fatal(err)
	}
	if calls["/repos/owner/unavailable"] != 2 || calls["/repos/owner/project"] != 1 {
		t.Fatal(calls)
	}
	s.now = func() time.Time { return clock.Add(10 * time.Minute) }
	if err := s.CollectDue(context.Background(), g, nil); err != nil {
		t.Fatal(err)
	}
	if calls["/repos/owner/unavailable"] != 2 {
		t.Fatal("second failure did not double retry delay")
	}
}
