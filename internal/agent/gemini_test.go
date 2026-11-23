package agent

import "testing"

func TestGeminiUsesOnlyExactConversationIDs(t *testing.T) {
	const id = "a1b2c3d4-1234-5678-9abc-0123456789ab"
	if got := ResumeCommandFor("gemini", id); got != "gemini --resume "+id {
		t.Fatalf("resume: %q", got)
	}
	for _, input := range []string{"", "1", "latest", "a1b2c3d4", id + ";exit"} {
		if got := ResumeCommandFor("gemini", input); got != "" {
			t.Fatalf("accepted invalid conversation ID %q: %q", input, got)
		}
	}
	if !MatchesProcess(Get("gemini"), []string{"node", "/usr/lib/node_modules/@google/gemini-cli/bundle/gemini.js"}) {
		t.Fatal("did not recognize the npm executable")
	}
	if MatchesProcess(Get("gemini"), []string{"codex", "ask gemini to run a task"}) {
		t.Fatal("recognized prompt text as a Gemini process")
	}
}
