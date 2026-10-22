package agentinventory

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/agent"
)

type UpgradePlan struct {
	Method  string   `json:"method"`
	Program string   `json:"-"`
	Args    []string `json:"-"`
}

var professionalMaintenance = make(chan struct{}, 1)

func ProfessionalUpgradePlan(kind string) (UpgradePlan, error) {
	path, err := agent.ResolveBinary(kind)
	if err != nil {
		return UpgradePlan{}, fmt.Errorf("AGENT_NOT_INSTALLED")
	}
	if kind == "opencode" {
		return UpgradePlan{Method: "native", Program: path, Args: []string{"upgrade"}}, nil
	}
	packages := map[string]string{"claude": "@anthropic-ai/claude-code", "codex": "@openai/codex", "pi": "@earendil-works/pi-coding-agent"}
	pkg, ok := packages[kind]
	if !ok {
		return UpgradePlan{}, fmt.Errorf("INVALID_AGENT_KIND")
	}
	real, err := filepath.EvalSymlinks(path)
	if err != nil {
		return UpgradePlan{}, fmt.Errorf("AGENT_UPGRADE_UNSUPPORTED")
	}
	for dir := filepath.Dir(real); dir != filepath.Dir(dir); dir = filepath.Dir(dir) {
		if filepath.Base(dir) != filepath.Base(pkg) || filepath.Base(filepath.Dir(filepath.Dir(dir))) != "node_modules" {
			continue
		}
		var manifest struct {
			Name string `json:"name"`
		}
		data, readErr := os.ReadFile(filepath.Join(dir, "package.json"))
		if readErr != nil || json.Unmarshal(data, &manifest) != nil || manifest.Name != pkg {
			continue
		}
		nodeModules := filepath.Dir(filepath.Dir(dir))
		prefix := filepath.Dir(nodeModules)
		if filepath.Base(prefix) == "lib" {
			prefix = filepath.Dir(prefix)
		}
		// A different package manager must update its own global directory.
		if strings.Contains(filepath.ToSlash(prefix), "/.bun/") || strings.Contains(filepath.ToSlash(prefix), "/pnpm/") {
			return UpgradePlan{}, fmt.Errorf("AGENT_UPGRADE_UNSUPPORTED")
		}
		program, lookupErr := exec.LookPath("npm")
		if lookupErr != nil {
			return UpgradePlan{}, fmt.Errorf("AGENT_UPGRADE_UNSUPPORTED")
		}
		args := []string{"install", "-g", "--prefix", prefix}
		if kind == "pi" {
			args = append(args, "--ignore-scripts")
		}
		return UpgradePlan{Method: "npm", Program: program, Args: append(args, pkg)}, nil
	}
	if kind == "claude" {
		return UpgradePlan{Method: "native", Program: path, Args: []string{"update"}}, nil
	}
	return UpgradePlan{}, fmt.Errorf("AGENT_UPGRADE_UNSUPPORTED")
}

func UpgradeProfessionalAgent(ctx context.Context, kind string) (ProfessionalAgent, error) {
	if agent.Get(kind) == nil {
		return ProfessionalAgent{}, fmt.Errorf("INVALID_AGENT_KIND")
	}
	select {
	case professionalMaintenance <- struct{}{}:
		defer func() { <-professionalMaintenance }()
	default:
		return ProfessionalAgent{}, fmt.Errorf("AGENT_MAINTENANCE_BUSY")
	}
	plan, err := ProfessionalUpgradePlan(kind)
	if err != nil {
		return ProfessionalAgent{}, err
	}
	command := exec.CommandContext(ctx, plan.Program, plan.Args...)
	if err = command.Run(); err != nil {
		return ProfessionalAgent{}, fmt.Errorf("AGENT_UPGRADE_FAILED")
	}
	professionalVersions.Lock()
	delete(professionalVersions.entries, kind)
	professionalVersions.Unlock()
	row, err := CheckProfessionalAgent(ctx, kind)
	if err != nil || !row.Installed || row.VersionState != "available" {
		return row, fmt.Errorf("AGENT_UPGRADE_UNVERIFIED")
	}
	return row, nil
}
