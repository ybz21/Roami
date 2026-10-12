package api

import "testing"

func TestProcStatStopped(t *testing.T) {
	for _, tc := range []struct {
		stat    string
		stopped bool
	}{
		{"3332571 (open code) T 3467198", true},
		{"3332571 (open code) t 3467198", true},
		{"3683588 (opencode) S 3467198", false},
		{"3683588 (opencode) R 3467198", false},
		{"malformed", false},
	} {
		if got := procStatStopped(tc.stat); got != tc.stopped {
			t.Errorf("procStatStopped(%q) = %v, want %v", tc.stat, got, tc.stopped)
		}
	}
}
