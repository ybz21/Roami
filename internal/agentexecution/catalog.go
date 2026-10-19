package agentexecution

import (
	"fmt"
	"os/exec"
	"regexp"
	"time"

	"github.com/ybz21/Roami/internal/agent"
)

type ExecutorCandidate struct {
	Kind           string `json:"kind"`
	Installed      bool   `json:"installed"`
	Tracked        bool   `json:"tracked"`
	Authentication string `json:"authentication"`
	Usage          string `json:"usage"`
}

type ExecutorCatalog struct {
	Version             int                 `json:"version"`
	ObservedMS          int64               `json:"observedMs"`
	DefaultExecutor     string              `json:"defaultExecutor,omitempty"`
	Candidates          []ExecutorCandidate `json:"candidates"`
	CommandAvailability map[string]bool     `json:"commandAvailability,omitempty"`
}

// Discovery never invokes providers or treats installation as authentication.
func DiscoverExecutors() ExecutorCatalog {
	result := ExecutorCatalog{Version: 1, ObservedMS: time.Now().UnixMilli(), Candidates: []ExecutorCandidate{}}
	for _, kind := range agent.Kinds() {
		_, err := exec.LookPath(agent.Get(kind).Bin())
		result.Candidates = append(result.Candidates, ExecutorCandidate{
			Kind: kind, Installed: err == nil, Tracked: kind == "codex" || kind == "claude",
			Authentication: "unknown", Usage: "unknown",
		})
	}
	if preferred := agent.Default(); preferred != nil {
		result.DefaultExecutor = preferred.Kind()
	}
	return result
}

func (c *ExecutorCatalog) ProbeCommands(commands []string) error {
	if len(commands) > 24 {
		return fmt.Errorf("INVALID_EXECUTOR_COMMANDS")
	}
	valid := regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+-]{0,100}$`)
	for _, name := range commands {
		if !valid.MatchString(name) {
			return fmt.Errorf("INVALID_EXECUTOR_COMMANDS")
		}
	}
	c.CommandAvailability = map[string]bool{}
	for _, name := range commands {
		_, err := exec.LookPath(name)
		c.CommandAvailability[name] = err == nil
	}
	return nil
}
