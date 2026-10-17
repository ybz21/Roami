// Package gitcontext detaches child commands from the caller's repository binding.
package gitcontext

import "strings"

func ForDirectory(environment []string) []string {
	result := make([]string, 0, len(environment))
	for _, entry := range environment {
		name, _, _ := strings.Cut(entry, "=")
		switch name {
		case "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
			"GIT_COMMON_DIR", "GIT_PREFIX", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
			"GIT_IMPLICIT_WORK_TREE", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE":
			continue
		}
		result = append(result, entry)
	}
	return result
}
