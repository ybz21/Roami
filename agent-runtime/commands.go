// Package agentcommands owns the public paths for context-bound Agent operations.
package agentcommands

import (
	_ "embed"
	"encoding/json"
)

//go:embed src/roami_agent/commands.json
var definition []byte

//go:embed src/roami_okr/commands.json
var projectDefinition []byte

func Paths() map[string][]string {
	var paths map[string][]string
	for _, entry := range [][]byte{definition, projectDefinition} {
		if err := json.Unmarshal(entry, &paths); err != nil {
			panic(err)
		}
	}
	return paths
}
