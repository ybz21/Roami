package session

import (
	"encoding/json"
	"fmt"
	"io"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func Pause(rt runtime.Runtime, args []string, pause bool, w io.Writer) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: roami session pause|resume <session> [--json]")
	}
	if err := rt.SetPaused(args[0], pause, "manual"); err != nil {
		return err
	}
	return json.NewEncoder(w).Encode(map[string]bool{"paused": pause})
}
