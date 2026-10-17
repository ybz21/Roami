package agentexecution

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Go's test cache must observe sources and migrations executed by Python children.
func recordRuntimeSources(t *testing.T, repository, scenario string) {
	t.Helper()
	for _, directory := range []string{"src", "migrations"} {
		err := filepath.WalkDir(filepath.Join(repository, "agent-runtime", directory), func(path string, entry fs.DirEntry, problem error) error {
			if problem != nil {
				return problem
			}
			if !entry.IsDir() && (strings.HasSuffix(path, ".py") || strings.HasSuffix(path, ".sql")) {
				_, problem = os.ReadFile(path)
			}
			return problem
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	if _, err := os.ReadFile(filepath.Join(repository, "agent-runtime", "tests", scenario)); err != nil {
		t.Fatal(err)
	}
}
