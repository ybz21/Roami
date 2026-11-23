package agent

import "github.com/google/uuid"

func init() { Register(gemini{}) }

type gemini struct{}

func (gemini) Kind() string             { return "gemini" }
func (gemini) DisplayName() string      { return "Gemini CLI" }
func (gemini) Bin() string              { return "gemini" }
func (gemini) PinsConversationID() bool { return true }
func (gemini) PromptFlag() string       { return "--prompt-interactive" }
func (gemini) InstallPackage() Package  { return Package{Name: "@google/gemini-cli"} }

func (g gemini) InteractiveArgs(opt StartOpts) []string {
	return append(g.OneShotArgs(opt), g.PromptFlag())
}

// Gemini CLI reads the headless prompt from stdin when no terminal is attached.
func (gemini) OneShotArgs(opt StartOpts) []string {
	var args []string
	if opt.Model != "" {
		args = append(args, "--model", opt.Model)
	}
	if opt.ConvID != "" {
		args = append(args, "--session-id", opt.ConvID)
	}
	switch opt.Permission {
	case "auto":
		args = append(args, "--approval-mode", "auto_edit")
	case "dangerously-skip-permissions":
		args = append(args, "--approval-mode", "yolo")
	case "plan":
		args = append(args, "--approval-mode", "plan")
	}
	return args
}

func (gemini) ResumeCommand(id string) string {
	if !ValidGeminiSessionID(id) {
		return ""
	}
	return "gemini --resume " + id
}

func (gemini) DetectConversationID(string) string { return "" }
func (gemini) ConversationDir(string) string      { return "" }

// Require a full UUID so Gemini cannot interpret the value as an index or "latest".
func ValidGeminiSessionID(id string) bool {
	parsed, err := uuid.Parse(id)
	return err == nil && parsed.String() == id
}
