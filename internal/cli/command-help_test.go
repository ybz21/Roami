package app

import (
	"bytes"
	"testing"
)

func TestCommandHelpPreservesLiteralArguments(t *testing.T) {
	for _, args := range [][]string{{"send", "session-id", "--help"}, {"sp", "-h"}, {"fork", "session-id", "--help"}} {
		if ShowHelp(args, &bytes.Buffer{}) {
			t.Fatalf("literal argument consumed as help: %v", args)
		}
	}
}
