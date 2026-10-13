package worktree

import (
	"context"
	"strconv"
	"strings"
	"sync"
	"time"
)

type ActivityCommit struct {
	OID string `json:"oid"`
	At  int64  `json:"at"`
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
	activityCache.Lock()
	cached, ok := activityCache.items[repo.CommonDir]
	activityCache.Unlock()
	if ok && time.Since(cached.at) < time.Minute {
		return cached.commits, nil
	}
	// Filter after walking: old Git lacks --since-as-filter, and --since skips newer ancestors after a backdated commit.
	out, err := git(ctx, repo.Root, "log", "--all", "--no-merges", "--format=%H%x09%ct")
	if err != nil {
		return nil, errf("GIT_ERROR", "%s", out)
	}
	commits := []ActivityCommit{}
	cutoff := time.Now().AddDate(0, 0, -370).Unix()
	for _, line := range strings.Split(out, "\n") {
		parts := strings.Split(line, "\t")
		if len(parts) != 2 {
			continue
		}
		at, err := strconv.ParseInt(parts[1], 10, 64)
		if err == nil && at >= cutoff {
			commits = append(commits, ActivityCommit{OID: parts[0], At: at})
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
