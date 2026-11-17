package agent

import "testing"

func TestRegisteredHarnessProcessIdentity(t *testing.T) {
	for _, tc := range []struct {
		argv []string
		want bool
	}{
		{[]string{"/opt/bin/pi", "--print", "codex should help"}, true},
		{[]string{"node", "/usr/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js", "--print"}, true},
		{[]string{"codex", "pi --print"}, false},
		{[]string{"bash", "-lc", "pi --print"}, false},
		{[]string{"node", "/tmp/pi-notes.js", "pi"}, false},
	} {
		if got := MatchesProcess(Get("pi"), tc.argv); got != tc.want {
			t.Errorf("%q: %v, want %v", tc.argv, got, tc.want)
		}
	}
}
