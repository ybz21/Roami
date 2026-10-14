package api

import (
	"github.com/gin-gonic/gin"
	"net/http"
	"sort"
	"strconv"
)

func (a *API) DayActivity(c *gin.Context) {
	from, fromErr := strconv.ParseInt(c.Query("from"), 10, 64)
	to, toErr := strconv.ParseInt(c.Query("to"), 10, 64)
	if fromErr != nil || toErr != nil || from < 0 || to <= from || to-from > 48*60*60 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_DATE_RANGE"}})
		return
	}
	if a.GitFootprints == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "HISTORY_UNAVAILABLE"}})
		return
	}
	commits, err := a.GitFootprints.Day(c.Request.Context(), from, to)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "HISTORY_UNAVAILABLE"}})
		return
	}
	events, failed := a.Footprints.Snapshot()
	dialogues, tasks := 0, 0
	for _, event := range events {
		if event.At >= from && event.At < to {
			dialogues += event.Dialogues
			tasks += event.Tasks
		}
	}
	counts := map[string]int{}
	for _, commit := range commits {
		counts[commit.Repo]++
	}
	projects := []DayProjectCount{}
	for repo, count := range counts {
		projects = append(projects, DayProjectCount{Repo: repo, Count: count})
	}
	sort.Slice(projects, func(i, j int) bool {
		if projects[i].Count == projects[j].Count {
			return projects[i].Repo < projects[j].Repo
		}
		return projects[i].Count > projects[j].Count
	})
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"projects": projects, "commits": len(commits), "dialogues": dialogues, "tasks": tasks, "recordingFailed": failed}})
}

type DayProjectCount struct {
	Repo  string `json:"repo"`
	Count int    `json:"count"`
}
