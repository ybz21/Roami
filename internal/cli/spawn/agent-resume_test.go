package spawn

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestResumeInteractiveSubmitsExactProviderAndLiteralPrompt(t *testing.T) {
	for _, kind := range []string{"codex", "claude"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			bin := filepath.Join(root, "capture")
			output := filepath.Join(root, "arguments")
			script := "#!/bin/sh\nprintf '%s\\n' \"$@\" > '" + output + "'\n"
			if err := os.WriteFile(bin, []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			prompt := filepath.Join(root, "prompt ' quotes.txt")
			text := "Continue exactly\n$(touch must-not-exist); `touch also-not-created`"
			if err := os.WriteFile(prompt, []byte(text), 0600); err != nil {
				t.Fatal(err)
			}
			config := DefaultAgentConfig(root)
			config.Kind, config.ClaudeBin, config.CodexBin, config.Model = kind, bin, bin, "selected-model"
			config.Permission = "auto"
			config.SessionUUID = "00000000-0000-4000-8000-000000000001"
			command := config.ResumeInteractiveFromPromptFile(config.SessionUUID, prompt)
			if data, err := exec.Command("/bin/sh", "-c", command).CombinedOutput(); err != nil {
				t.Fatalf("resume command: %v %s", err, data)
			}
			args, err := os.ReadFile(output)
			if err != nil || !strings.HasSuffix(string(args), text+"\n") {
				t.Fatalf("prompt changed: %s %v", args, err)
			}
			flag := "resume"
			if kind == "claude" {
				flag = "--resume"
				if strings.Contains(string(args), "--session-id") {
					t.Fatal("resume created a fresh Claude UUID")
				}
			}
			if !strings.Contains(string(args), flag+"\n"+config.SessionUUID+"\n") || !strings.Contains(string(args), "selected-model\n") {
				t.Fatalf("wrong provider/model: %s", args)
			}
			for _, name := range []string{"must-not-exist", "also-not-created"} {
				if _, err := os.Stat(filepath.Join(root, name)); !os.IsNotExist(err) {
					t.Fatal("prompt executed as shell code")
				}
			}
		})
	}
}
