package swarm

import (
	"fmt"
	"io"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func Run(rt runtime.Runtime, args []string, w io.Writer) error {
	command := "ls"
	if len(args) > 0 {
		command, args = args[0], args[1:]
	}
	if handled, err := managedCommand(rt, command, args, w); handled {
		return err
	}
	return fmt.Errorf("unsupported swarm command: %s; use new, ls, status, plan, dependencies, control, say or post", command)
}
