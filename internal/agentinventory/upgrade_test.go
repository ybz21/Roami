package agentinventory

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestNativeOpenCodeUpgradeUsesDiscoveredInstallation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PATH", t.TempDir())
	bin := filepath.Join(home, ".opencode", "bin", "opencode")
	version := filepath.Join(home, "version")
	if err := os.MkdirAll(filepath.Dir(bin), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(version, []byte("opencode v2.0.27"), 0600); err != nil {
		t.Fatal(err)
	}
	script := "#!/bin/sh\ncase \"$1\" in\n--version) /bin/cat '" + version + "';;\nupgrade) printf 'opencode v2.0.28' > '" + version + "';;\n*) exit 1;;\nesac\n"
	if err := os.WriteFile(bin, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	plan, err := ProfessionalUpgradePlan("opencode")
	if err != nil || plan.Program != bin || !reflect.DeepEqual(plan.Args, []string{"upgrade"}) {
		t.Fatalf("wrong native upgrade: %+v, %v", plan, err)
	}
	row, err := UpgradeProfessionalAgent(context.Background(), "opencode")
	if err != nil || row.Binary != bin || row.Version != "opencode v2.0.28" || !row.CanUpgrade {
		t.Fatalf("upgrade not verified: %+v, %v", row, err)
	}
	professionalMaintenance <- struct{}{}
	_, err = UpgradeProfessionalAgent(context.Background(), "opencode")
	<-professionalMaintenance
	if err == nil || err.Error() != "AGENT_MAINTENANCE_BUSY" {
		t.Fatalf("concurrent upgrade accepted: %v", err)
	}
}

func TestNPMUpgradeKeepsOriginalPrefix(t *testing.T) {
	for _, kind := range []string{"claude", "codex", "pi"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			pkg := "@openai/codex"
			if kind == "claude" {
				pkg = "@anthropic-ai/claude-code"
			}
			if kind == "pi" {
				pkg = "@earendil-works/pi-coding-agent"
			}
			prefix := filepath.Join(root, "custom-prefix")
			binDir := filepath.Join(prefix, "bin")
			packageDir := filepath.Join(prefix, "lib", "node_modules", filepath.FromSlash(pkg))
			if err := os.MkdirAll(binDir, 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.MkdirAll(packageDir, 0700); err != nil {
				t.Fatal(err)
			}
			for path, data := range map[string]string{filepath.Join(packageDir, "cli.js"): "#!/bin/sh\nexit 0\n", filepath.Join(packageDir, "package.json"): `{"name":"` + pkg + `"}`, filepath.Join(binDir, "npm"): "#!/bin/sh\nexit 0\n"} {
				if err := os.WriteFile(path, []byte(data), 0700); err != nil {
					t.Fatal(err)
				}
			}
			if err := os.Symlink(filepath.Join(packageDir, "cli.js"), filepath.Join(binDir, kind)); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", binDir)
			plan, err := ProfessionalUpgradePlan(kind)
			if err != nil || plan.Method != "npm" || !strings.Contains(strings.Join(plan.Args, " "), "--prefix "+prefix) || plan.Args[len(plan.Args)-1] != pkg {
				t.Fatalf("upgrade changed prefix: %+v, %v", plan, err)
			}
		})
	}
}

func TestUnknownUpgradeInstallationDoesNotRunPackageManager(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("PATH", dir)
	if err := os.WriteFile(filepath.Join(dir, "codex"), []byte("#!/bin/sh\nexit 0\n"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := ProfessionalUpgradePlan("codex"); err == nil || err.Error() != "AGENT_UPGRADE_UNSUPPORTED" {
		t.Fatalf("unknown install accepted: %v", err)
	}
	if _, err := UpgradeProfessionalAgent(context.Background(), "unknown"); err == nil || err.Error() != "INVALID_AGENT_KIND" {
		t.Fatalf("unknown agent accepted: %v", err)
	}
}
