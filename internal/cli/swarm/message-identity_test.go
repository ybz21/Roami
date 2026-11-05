package swarm

import (
	"io"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestAgentShellCannotPostAsHuman(t *testing.T) {
	for _, role := range []string{"main", "worker", "research"} {
		t.Run(role, func(t *testing.T) {
			t.Setenv("ROAMI_AGENT_CALLER_ROLE", role)
			err := Run(runtime.Runtime{}, []string{"say", "sw-0123456789abcdef0123456789abcdef", "Progress verified", "--key", "progress"}, io.Discard)
			if err == nil || !strings.Contains(err.Error(), "AGENT_MESSAGE_IDENTITY_REQUIRED") {
				t.Fatal("must reject before opening a runtime client", err)
			}
		})
	}
}
