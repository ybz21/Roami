// Package agentcommands owns the public paths for context-bound Agent operations.
package agentcommands

import (
	_ "embed"
	"encoding/json"
)

//go:embed src/roami_agent/commands.json
var definition []byte

func Paths() map[string][]string {
	var paths map[string][]string
	if err := json.Unmarshal(definition, &paths); err != nil {
		panic(err)
	}
	return paths
}
