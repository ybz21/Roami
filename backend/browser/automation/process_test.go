package automation

import (
	"os"
	"os/exec"
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
