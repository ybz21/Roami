package agent

import (
	"os"
	"strings"

	"github.com/google/uuid"
)

const AntigravityAPIKeySettings = `{"modelProvider":"gemini"}`

func AntigravityManagedConfigured() bool {
	return strings.TrimSpace(os.Getenv("GEMINI_API_KEY")) != ""
}

func init() { Register(antigravity{}) }

type antigravity struct{}

func (antigravity) Kind() string             { return "antigravity" }
func (antigravity) DisplayName() string      { return "Antigravity CLI" }
func (antigravity) Bin() string              { return "agy" }
func (antigravity) PinsConversationID() bool { return false }
func (antigravity) PromptFlag() string       { return "--prompt-interactive" }
func (antigravity) OneShotPromptArg() bool   { return true }

func (a antigravity) Descriptor() Descriptor {
	return Descriptor{Command: a.Bin(), Interactive: true, CanInstall: true}
}

func (a antigravity) InteractiveArgs(opt StartOpts) []string {
	return append(AntigravityOptions(opt), a.PromptFlag())
}

func (antigravity) OneShotArgs(opt StartOpts) []string {
	return append(AntigravityOptions(opt), "--print")
}

func AntigravityOptions(opt StartOpts) []string {
	var args []string
	if opt.Model != "" {
		args = append(args, "--model", opt.Model)
	}
	switch opt.Permission {
	case "auto":
		args = append(args, "--mode", "accept-edits")
	case "dangerously-skip-permissions":
		args = append(args, "--dangerously-skip-permissions")
	case "plan":
		args = append(args, "--mode", "plan")
	}
	return args
}

func (antigravity) ResumeCommand(id string) string {
	if !ValidAntigravityConversationID(id) {
		return ""
	}
	return "agy --conversation " + id
}

func (antigravity) DetectConversationID(string) string { return "" }
func (antigravity) ConversationDir(string) string      { return "" }

func ValidAntigravityConversationID(id string) bool {
	parsed, err := uuid.Parse(id)
	return err == nil && parsed.String() == id
}
