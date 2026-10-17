package api

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var paneWorktreeFooter = regexp.MustCompile(`(?:^|/)\.worktrees/([A-Za-z0-9._-]+)(?::|\s|$)`)

func paneWorktreeDir(dir, capture string) string {
	lines := strings.Split(strings.TrimSpace(capture), "\n")
	if len(lines) > 4 {
		lines = lines[len(lines)-4:]
	}
	for i := len(lines) - 1; i >= 0; i-- {
		match := paneWorktreeFooter.FindStringSubmatch(lines[i])
		if len(match) != 2 {
			continue
		}
		root := filepath.Clean(dir)
		if before, _, ok := strings.Cut(root, string(filepath.Separator)+".worktrees"+string(filepath.Separator)); ok {
			root = before
		}
		candidate := filepath.Join(root, ".worktrees", match[1])
		if info, err := os.Stat(candidate); err == nil && info.IsDir() {
			return candidate
		}
	}
	return dir
}
