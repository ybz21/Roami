package session

import (
	"fmt"
	"io"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// ValidKey is the shared CLI/HTTP contract for focused TUI interaction.
func ValidKey(key string) bool {
	switch key {
	case "Up", "Down", "Left", "Right", "Enter", "Escape", "Tab", "Space", "BSpace", "BTab", "C-c":
		return true
	}
	if len(key) != 1 {
		return false
	}
	ch := key[0]
	return ch >= '0' && ch <= '9' || ch >= 'a' && ch <= 'z' || ch >= 'A' && ch <= 'Z'
}

func Keys(rt runtime.Runtime, args []string, w io.Writer) error {
	if len(args) < 2 {
		return fmt.Errorf("usage: roami session keys <session> <key...>")
	}
	for _, key := range args[1:] {
		if !ValidKey(key) {
			return fmt.Errorf("unsupported session key %q", key)
		}
	}
	row, err := rt.ResolveStrict(args[0])
	if err != nil {
		return err
	}
	command := append([]string{"send-keys", "-t", "=" + row.Name + ":"}, args[1:]...)
	return rt.Tmux(command...)
}
