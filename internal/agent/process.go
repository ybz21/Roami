package agent

import (
	"path/filepath"
	"strings"
)

// MatchesProcess inspects executable paths only; prompt text cannot select a harness.
func MatchesProcess(a Agent, argv []string) bool {
	if len(argv) == 0 {
		return false
	}
	script := argv[0]
	switch filepath.Base(script) {
	case "node", "nodejs", "bun", "deno":
		if len(argv) < 2 {
			return false
		}
		script = argv[1]
	}
	if filepath.Base(script) == a.Bin() {
		return true
	}
	if pkg, ok := InstallPackage(a.Kind()); ok {
		return strings.Contains(filepath.ToSlash(script), "/node_modules/"+pkg.Name+"/")
	}
	return false
}
