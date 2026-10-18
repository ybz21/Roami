package automation

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestStableTargetSelectionAndSingleAttempt(t *testing.T) {
	if _, err := exec.LookPath("node"); err != nil {
		t.Skip("Node.js is required for Chrome automation")
	}
	for _, name := range []string{"driver.mjs", "target-selection.test.mjs", "operation-receipts.mjs", "operation-receipts.test.mjs", "browser-observation.mjs", "browser-observation.test.mjs"} {
		if _, err := os.ReadFile(name); err != nil {
			t.Fatal(err)
		}
	}
	output, err := exec.Command("node", "--test", "target-selection.test.mjs", "operation-receipts.test.mjs", "browser-observation.test.mjs").CombinedOutput()
	if err != nil {
		t.Fatalf("Chrome contract tests: %v\n%s", err, output)
	}
}

func TestFirstRunDependencyOutputDoesNotPolluteJSON(t *testing.T) {
	root := t.TempDir()
	bins := filepath.Join(root, "bin")
	if err := os.MkdirAll(bins, 0700); err != nil {
		t.Fatal(err)
	}
	programs := map[string]string{
		"npm":  "#!/bin/sh\nmkdir -p node_modules/playwright-core\nprintf 'added installer package\\n'\n",
		"node": "#!/bin/sh\nprintf '{\"version\":\"fixture\"}\\n'\n",
		"curl": "#!/bin/sh\nexit 0\n",
	}
	for name, content := range programs {
		if err := os.WriteFile(filepath.Join(bins, name), []byte(content), 0700); err != nil {
			t.Fatal(err)
		}
	}
	path := filepath.Join(root, "launcher")
	if err := os.WriteFile(path, []byte(launcher), 0700); err != nil {
		t.Fatal(err)
	}
	command := exec.Command("bash", path, "capabilities", "--cdp", "http://127.0.0.1:1")
	command.Env = append(os.Environ(), "PATH="+bins+string(os.PathListSeparator)+os.Getenv("PATH"), "ROAMI_DATA="+root, "ROAMI_HOME="+root)
	var diagnostics bytes.Buffer
	command.Stderr = &diagnostics
	output, err := command.Output()
	if err != nil {
		t.Fatalf("first run: %v %s", err, diagnostics.String())
	}
	var result map[string]string
	if err = json.Unmarshal(output, &result); err != nil || result["version"] != "fixture" {
		t.Fatalf("dirty JSON output %q: %v", output, err)
	}
	if !strings.Contains(diagnostics.String(), "added installer package") {
		t.Fatal("installer diagnostics were lost")
	}
}
