package agentexecution

import "regexp"

var claudePastedInput = regexp.MustCompile(`(?s)^\n\n<pasted_content id="([A-Za-z0-9_-]{1,64})">\n(.*)\n</pasted_content id="([A-Za-z0-9_-]{1,64})">\n$`)

// Claude can wrap a long bracketed paste; only the exact expected payload qualifies.
func claudeInputHash(input, expected string) string {
	raw := workspaceHash(input)
	if raw == expected {
		return raw
	}
	match := claudePastedInput.FindStringSubmatch(input)
	if len(match) == 4 && match[1] == match[3] {
		// Claude's paste wrapper can consume one final newline from the submitted text.
		if workspaceHash(match[2]) == expected || workspaceHash(match[2]+"\n") == expected {
			return expected
		}
	}
	return raw
}
