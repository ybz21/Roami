package memrelief

import "strings"

func emptyPrompt(kind, screen string, cursorY int) bool {
	lines := strings.Split(strings.ReplaceAll(screen, "\r", ""), "\n")
	if cursorY < 0 || cursorY >= len(lines) {
		return false
	}
	mark := "›"
	if kind == "claude" {
		mark = "❯"
	}
	line := strings.TrimSpace(lines[cursorY])
	// Codex can put the empty composer cursor on the line below its marker.
	emptyNextLine := line == "" && cursorY > 0 && strings.TrimSpace(lines[cursorY-1]) == mark
	if line != mark && !emptyNextLine {
		return false
	}
	start := len(lines) - 12
	if start < 0 {
		start = 0
	}
	footer := strings.ToLower(strings.Join(lines[start:], "\n"))
	for _, text := range []string{"esc to interrupt", "esc to cancel", "esc to stop", "working (", "running…", "allow this", "approve", "accept edits", "permission required", "是否允许", "正在思考"} {
		if strings.Contains(footer, text) {
			return false
		}
	}
	return true
}
