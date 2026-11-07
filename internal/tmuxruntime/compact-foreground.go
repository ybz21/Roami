package runtime

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/memguard"
)

func compactLaunchKind(argv []string) string {
	if len(argv) == 0 {
		return ""
	}
	name := filepath.Base(argv[0])
	launch := argv[0]
	if name == "node" || name == "nodejs" || name == "bun" {
		if len(argv) < 2 {
			return ""
		}
		launch = argv[1]
		name = filepath.Base(launch)
	}
	for i := 1; i < len(argv) && i < 3; i++ {
		if argv[i] == "app-server" || argv[i] == "mcp-server" || argv[i] == "exec" || argv[i] == "-p" || argv[i] == "--print" {
			return ""
		}
	}
	if name == "claude" || strings.Contains(launch, "/@anthropic-ai/claude-code/") {
		return "claude"
	}
	if name == "codex" || strings.Contains(launch, "/@openai/codex/") {
		return "codex"
	}
	return ""
}

func processGroups(pid int) (group, foreground string) {
	b, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	if err != nil {
		return
	}
	i := strings.LastIndexByte(string(b), ')')
	if i < 0 {
		return
	}
	f := strings.Fields(string(b[i+1:]))
	if len(f) > 5 {
		return f[2], f[5]
	}
	return
}

func foregroundCompactKind(panePID int) string {
	_, foreground := processGroups(panePID)
	if foreground == "" || foreground == "-1" {
		return ""
	}
	_, pids, err := memguard.ScopeProcesses(panePID)
	if err != nil {
		return ""
	}
	kind := ""
	for _, pid := range pids {
		group, _ := processGroups(pid)
		if group != foreground {
			continue
		}
		b, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/cmdline")
		if err != nil {
			continue
		}
		if k := compactLaunchKind(strings.Split(strings.TrimRight(string(b), "\x00"), "\x00")); k != "" {
			if kind != "" && kind != k {
				return ""
			}
			kind = k
		}
	}
	return kind
}
