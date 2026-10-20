package agentinventory

import (
	"context"
	"fmt"
	"os/exec"

	"github.com/ybz21/Roami/internal/agent"
)

type ProfessionalAgent struct {
	Kind      string     `json:"kind"`
	Installed bool       `json:"installed"`
	Quota     AgentQuota `json:"quota"`
}

func DiscoverProfessionalAgents(ctx context.Context) []ProfessionalAgent {
	rows := make([]ProfessionalAgent, 0)
	for _, kind := range agent.Kinds() {
		_, err := exec.LookPath(agent.Get(kind).Bin())
		installed := err == nil
		q := AgentQuota{State: "unknown", Reason: "provider_managed"}
		if installed {
			switch kind {
			case "codex":
				q = codexQuota()
				if q.State == "unknown" {
					q.Reason = "no_snapshot"
				}
			case "claude":
				q = claudeQuota(ctx)
			}
		}
		rows = append(rows, ProfessionalAgent{Kind: kind, Installed: installed, Quota: q})
	}
	return rows
}

func ProfessionalInstallArgs(kind string) ([]string, error) {
	packages := map[string]string{
		"claude": "@anthropic-ai/claude-code", "codex": "@openai/codex",
		"pi": "@earendil-works/pi-coding-agent", "opencode": "opencode-ai",
	}
	pkg, ok := packages[kind]
	if !ok {
		return nil, fmt.Errorf("INVALID_AGENT_KIND")
	}
	args := []string{"install", "-g"}
	if kind == "pi" {
		args = append(args, "--ignore-scripts")
	}
	return append(args, pkg), nil
}

func InstallProfessionalAgent(ctx context.Context, args []string) error {
	return exec.CommandContext(ctx, "npm", args...).Run()
}
