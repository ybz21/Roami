package main

import (
	"fmt"
	"net/url"
)

func agentHistoryPath(conversation string, limit int, before, branch string) (string, error) {
	if limit < 1 || limit > 100 {
		return "", fmt.Errorf("history --limit must be between 1 and 100")
	}
	query := url.Values{"limit": {fmt.Sprint(limit)}}
	if before != "" {
		query.Set("before", before)
	}
	if branch != "" {
		query.Set("branch", branch)
	}
	return "/v1/conversations/" + url.PathEscape(conversation) + "/messages?" + query.Encode(), nil
}
