package session

import (
	"encoding/json"
	"fmt"
	"github.com/ybz21/Roami/internal/memguard"
	"github.com/ybz21/Roami/internal/tmuxruntime"
	"io"
)

func MemoryRecovery(rt runtime.Runtime, args []string, command string, w io.Writer) error {
	switch command {
	case "memory-status":
		return json.NewEncoder(w).Encode(memguard.Compression())
	case "memory-setup-script":
		_, err := w.Write(memguard.CompressionSetup)
		return err
	}
	if len(args) == 0 {
		return fmt.Errorf("usage: roami session %s <session> [--json]", command)
	}
	if command == "compact" {
		state, err := rt.CompactSession(args[0], false)
		if err != nil {
			return err
		}
		return json.NewEncoder(w).Encode(state)
	}
	state, err := rt.ReclaimSession(args[0], false)
	if err != nil {
		return err
	}
	return json.NewEncoder(w).Encode(state)
}
