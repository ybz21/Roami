package worktree

import (
	"context"
	"strconv"
	"strings"
	"sync"
	"time"
)

type ActivityCommit struct {
	OID     string `json:"oid"`
	At      int64  `json:"at"`
	Repo    string `json:"-"`
	Subject string `json:"-"`
}

var activityCache = struct {
	sync.Mutex
	items map[string]struct {
		at      time.Time
		commits []ActivityCommit
	}
}{items: make(map[string]struct {
	at      time.Time
	commits []ActivityCommit
})}

// ActivityCommits includes every reachable branch, without the activity feed's 120-entry cap.
func (s *Service) ActivityCommits(ctx context.Context, repo Repo) ([]ActivityCommit, error) {
	commits, err := s.AllActivityCommits(ctx, repo)
	if err != nil {
		return nil, err
	}
	recent := []ActivityCommit{}
	cutoff := time.Now().AddDate(0, 0, -370).Unix()
	for _, commit := range commits {
		if commit.At >= cutoff {
			recent = append(recent, commit)
		}
	}
	return recent, nil
}

func (s *Service) AllActivityCommits(ctx context.Context, repo Repo) ([]ActivityCommit, error) {
	activityCache.Lock()
	cached, ok := activityCache.items[repo.CommonDir]
	activityCache.Unlock()
	if ok && time.Since(cached.at) < time.Minute {
		return cached.commits, nil
	}
	// Walk all history for durable backfill, including ancestors beyond backdated commits.
	out, err := git(ctx, repo.Root, "log", "--all", "--no-merges", "--format=%H%x09%ct%x09%s")
	if err != nil {
		return nil, errf("GIT_ERROR", "%s", out)
	}
	commits := []ActivityCommit{}
	for _, line := range strings.Split(out, "\n") {
		parts := strings.SplitN(line, "\t", 3)
		if len(parts) != 3 {
			continue
		}
		at, err := strconv.ParseInt(parts[1], 10, 64)
		if err == nil {
			commits = append(commits, ActivityCommit{OID: parts[0], At: at, Repo: repo.Root, Subject: parts[2]})
		}
	}
	activityCache.Lock()
	activityCache.items[repo.CommonDir] = struct {
		at      time.Time
		commits []ActivityCommit
	}{time.Now(), commits}
	activityCache.Unlock()
	return commits, nil
}
