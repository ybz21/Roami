package spawn

import (
	"strings"
	"testing"
)

func TestRegisteredPromptFileLaunches(t *testing.T) {
	for _, tc := range []struct{ kind, prefix string }{
		{"pi", "pi --print"},
		{"opencode", "opencode run"},
	} {
		t.Run(tc.kind, func(t *testing.T) {
			c := DefaultAgentConfig("/tmp")
			c.Kind = tc.kind
			got := c.CommandFromPromptFile("/tmp/agent prompt")
			if !strings.Contains(got, tc.prefix) || !strings.Contains(got, `"$(cat '/tmp/agent prompt')"`) {
				t.Fatalf("wrong launch: %s", got)
			}
		})
	}
}
