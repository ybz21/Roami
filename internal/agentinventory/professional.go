package agentinventory

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/agent"
)

type ProfessionalAgent struct {
	Kind           string     `json:"kind"`
	Installed      bool       `json:"installed"`
	Binary         string     `json:"binary,omitempty"`
	Version        string     `json:"version,omitempty"`
	VersionState   string     `json:"versionState,omitempty"`
	Authentication string     `json:"authentication"`
	Quota          AgentQuota `json:"quota"`
}

func DiscoverProfessionalAgents(ctx context.Context) []ProfessionalAgent {
	rows := make([]ProfessionalAgent, 0)
	for _, kind := range agent.Kinds() {
		rows = append(rows, discoverProfessionalAgent(ctx, kind))
	}
	return rows
}

func discoverProfessionalAgent(ctx context.Context, kind string) ProfessionalAgent {
	path, err := exec.LookPath(agent.Get(kind).Bin())
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
	authentication := "unknown"
	if q.Reason == "login_required" {
		authentication = "required"
	}
	if q.Reason == "login_expired" {
		authentication = "expired"
	}
	return ProfessionalAgent{Kind: kind, Installed: installed, Binary: path, Authentication: authentication, Quota: q}
}

// Version probes are explicit; automatic status reads never start a CLI.
func CheckProfessionalAgent(ctx context.Context, kind string) (ProfessionalAgent, error) {
	if agent.Get(kind) == nil {
		return ProfessionalAgent{}, fmt.Errorf("INVALID_AGENT_KIND")
	}
	row := discoverProfessionalAgent(ctx, kind)
	if !row.Installed {
		return row, nil
	}
	row.VersionState = "unavailable"
	row.Version = probeProfessionalVersion(ctx, row.Binary)
	if row.Version != "" {
		row.VersionState = "available"
	}
	return row, nil
}

type versionOutput struct{ text []byte }

func (out *versionOutput) Write(data []byte) (int, error) {
	count := len(data)
	if remaining := 4096 - len(out.text); remaining > 0 {
		out.text = append(out.text, data[:min(remaining, len(data))]...)
	}
	return count, nil
}

func probeProfessionalVersion(ctx context.Context, path string) string {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, path, "--version")
	command.WaitDelay = 100 * time.Millisecond
	output := &versionOutput{}
	command.Stdout = output
	if command.Run() != nil {
		return ""
	}
	version := strings.TrimSpace(strings.SplitN(string(output.text), "\n", 2)[0])
	if len(version) > 256 {
		return ""
	}
	return version
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
