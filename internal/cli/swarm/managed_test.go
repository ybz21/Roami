package swarm

import (
	"io"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestManagedCommandsRejectLegacyCompletion(t *testing.T) {
	for _, command := range []string{"done", "add", "adopt", "activate"} {
		handled, err := managedCommand(runtime.Runtime{}, command, []string{"sw-0123456789abcdef0123456789abcdef"}, io.Discard)
		if !handled || err == nil || !strings.Contains(err.Error(), "MANAGED_SWARM_USES_MAIN") {
			t.Fatalf("%s must use managed orchestration: handled=%v err=%v", command, handled, err)
		}
	}
}

func TestManagedCreationRequiresIdempotencyKey(t *testing.T) {
	handled, err := managedCommand(runtime.Runtime{}, "new", []string{"team", "--main-conversation", "main", "--goal", "build"}, io.Discard)
	if !handled || err == nil || !strings.Contains(err.Error(), "requires --key") {
		t.Fatalf("creation must be safely retryable: handled=%v err=%v", handled, err)
	}
}
