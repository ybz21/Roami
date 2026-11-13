package agent

import (
	"slices"
	"testing"
)

func TestDeepSeekRegistration(t *testing.T) {
	a := Get("deepseek")
	if a == nil || a.Bin() != "dsh" || a.PinsConversationID() || !slices.Contains(Kinds(), "deepseek") {
		t.Fatal("DeepSeek is not registered as dsh")
	}
	d := Describe(a)
	if d.DisplayName != "DeepSeek Harness" || d.Command != "dsh --profile headless --permission-mode danger-full-access" || d.Interactive || d.Models || !d.CanInstall {
		t.Fatalf("unsupported capabilities advertised: %+v", d)
	}
	if ResumeCommandFor("deepseek", "conversation") != "" {
		t.Fatal("must not fabricate a resume command")
	}
}

func TestRegisteredHarnessProcessIdentity(t *testing.T) {
	for _, tc := range []struct {
		argv []string
		want bool
	}{
		{[]string{"/opt/bin/dsh", "--profile", "headless", "codex should help"}, true},
		{[]string{"node", "/usr/lib/node_modules/@deepseek-ai/dsh/dist/bin.js", "--profile", "headless"}, true},
		{[]string{"codex", "dsh --profile headless --permission-mode danger-full-access"}, false},
		{[]string{"bash", "-lc", "dsh --profile headless --permission-mode danger-full-access"}, false},
		{[]string{"node", "/tmp/deepseek-notes.js", "dsh"}, false},
	} {
		if got := MatchesProcess(Get("deepseek"), tc.argv); got != tc.want {
			t.Errorf("%q: %v, want %v", tc.argv, got, tc.want)
		}
	}
}
