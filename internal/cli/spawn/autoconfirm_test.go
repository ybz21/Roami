package spawn

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestAutoconfirmCannotReachPrefixSibling(t *testing.T) {
	directory := t.TempDir()
	binary := filepath.Join(directory, "tmux")
	script := `#!/usr/bin/env python3
import pathlib, sys
root = pathlib.Path(__file__).parent
with (root / 'calls').open('a') as output:
    output.write(' '.join(sys.argv[1:]) + '\n')
if sys.argv[1] == 'capture-pane':
    print('trust this folder' if not (root / 'seen').exists() else 'Bypass Permissions mode')
    (root / 'seen').touch()
`
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	RunAutoconfirm(runtime.Runtime{TmuxBin: binary}, "worker")
	data, err := os.ReadFile(filepath.Join(directory, "calls"))
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) != 4 {
		t.Fatalf("missing dialog observations or replies: %s", data)
	}
	for _, line := range lines {
		if !strings.Contains(line, " -t =worker ") {
			t.Fatalf("dialog worker can target a prefix sibling: %s", line)
		}
	}
}
