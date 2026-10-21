package session

import (
	"github.com/ybz21/Roami/internal/tmuxruntime"
	"io"
	"testing"
)

func TestCloseRequiresOneExplicitTargetBeforeObservation(t *testing.T) {
	for _, args := range [][]string{nil, {"--yes"}, {"--yes", "--cascade"}, {"one", "two", "--yes"}} {
		if err := KillTree(runtime.Runtime{}, nil, nil, args, io.Discard); err == nil {
			t.Fatalf("missing or multiple targets accepted: %v", args)
		}
	}
}
