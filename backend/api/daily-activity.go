package api

import (
	"context"
	"errors"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	"ttmux-web/worktree"
)

func (a *API) DailyActivity(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 20*time.Second)
	defer cancel()
	commits := []worktree.ActivityCommit{}
	repos, seen := map[string]bool{}, map[string]bool{}
	failed, counted := 0, 0
	for _, entry := range a.Projects.Entries() {
		if _, err := os.Stat(entry.Dir); err != nil {
			failed++
			continue
		}
		projectCtx, projectCancel := context.WithTimeout(ctx, 3*time.Second)
		repo, err := a.WT.ResolveRepo(projectCtx, entry.Dir)
		if err != nil {
			timedOut := projectCtx.Err() != nil
			projectCancel()
			var we *worktree.Err
			if timedOut || !errors.As(err, &we) || we.Code != "NOT_GIT_REPO" {
				failed++
			}
			continue
		}
		if repos[repo.CommonDir] {
			projectCancel()
			continue
		}
		repos[repo.CommonDir] = true
		items, err := a.WT.AllActivityCommits(projectCtx, repo)
		projectCancel()
		if err != nil {
			failed++
			continue
		}
		counted++
		for _, commit := range items {
			// A clone or another registered worktree must not count the same commit twice.
			if !seen[commit.OID] {
				seen[commit.OID] = true
				commits = append(commits, commit)
			}
		}
	}
	commitHistoryFailed := false
	if a.GitFootprints != nil {
		if err := a.GitFootprints.Import(ctx, commits); err != nil {
			commitHistoryFailed = true
		}
		if archived, err := a.GitFootprints.Recent(ctx); err == nil {
			for _, commit := range archived {
				if !seen[commit.OID] {
					commits = append(commits, commit)
					seen[commit.OID] = true
				}
			}
		} else {
			commitHistoryFailed = true
		}
	}
	recent := []worktree.ActivityCommit{}
	cutoff := time.Now().AddDate(0, 0, -370).Unix()
	for _, commit := range commits {
		if commit.At >= cutoff {
			recent = append(recent, commit)
		}
	}
	commits = recent
	usage, recordingFailed := a.Footprints.Snapshot()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"commits": commits, "usage": usage, "recordingFailed": recordingFailed, "commitHistoryFailed": commitHistoryFailed, "repositories": counted, "failed": failed}})
}
