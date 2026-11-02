package agentinventory

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/agent"
)

type ProfessionalAgent struct {
	Verified       bool       `json:"verified"`
	Kind           string     `json:"kind"`
	Installed      bool       `json:"installed"`
	Binary         string     `json:"binary,omitempty"`
	Version        string     `json:"version,omitempty"`
	VersionState   string     `json:"versionState,omitempty"`
	Authentication string     `json:"authentication"`
	UpgradeMethod  string     `json:"upgradeMethod,omitempty"`
	CanUpgrade     bool       `json:"canUpgrade"`
	ModelPreset    string     `json:"modelPreset,omitempty"`
	Quota          AgentQuota `json:"quota"`
}

func DiscoverProfessionalAgents(ctx context.Context) []ProfessionalAgent {
	kinds := agent.Kinds()
	rows := make([]ProfessionalAgent, len(kinds))
	var pending sync.WaitGroup
	for i, kind := range kinds {
		pending.Add(1)
		go func() {
			defer pending.Done()
			rows[i] = discoverProfessionalAgent(ctx, kind)
			readProfessionalVersion(ctx, &rows[i], false)
		}()
	}
	pending.Wait()
	return rows
}

func discoverProfessionalAgent(ctx context.Context, kind string) ProfessionalAgent {
	path, err := agent.ResolveBinary(kind)
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
	row := ProfessionalAgent{Kind: kind, Installed: installed, Binary: path, Authentication: authentication, Quota: q}
	if installed {
		if plan, err := ProfessionalUpgradePlan(kind); err == nil {
			row.CanUpgrade, row.UpgradeMethod = true, plan.Method
		}
	}
	return row
}

// Explicit checks bypass completed cache entries and join any matching in-flight probe.
func CheckProfessionalAgent(ctx context.Context, kind string) (ProfessionalAgent, error) {
	if agent.Get(kind) == nil {
		return ProfessionalAgent{}, fmt.Errorf("INVALID_AGENT_KIND")
	}
	row := discoverProfessionalAgent(ctx, kind)
	readProfessionalVersion(ctx, &row, true)
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
	select {
	case professionalMaintenance <- struct{}{}:
		defer func() { <-professionalMaintenance }()
	default:
		return fmt.Errorf("AGENT_MAINTENANCE_BUSY")
	}
	if err := exec.CommandContext(ctx, "npm", args...).Run(); err != nil {
		return err
	}
	professionalVersions.Lock()
	clear(professionalVersions.entries)
	professionalVersions.Unlock()
	return nil
}
