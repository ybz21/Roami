package agent

import "strings"

func init() { Register(pi{}) }

type pi struct{}

func (pi) Kind() string             { return "pi" }
func (pi) DisplayName() string      { return "Pi" }
func (pi) Bin() string              { return "pi" }
func (pi) PinsConversationID() bool { return true }
func (pi) OneShotPromptArg() bool   { return true }
func (pi) InteractiveArgs(opt StartOpts) []string {
	var args []string
	if opt.Model != "" {
		args = append(args, "--model", opt.Model)
	}
	if opt.ConvID != "" {
		args = append(args, "--session-id", opt.ConvID)
	}
	return args
}
func (pi) OneShotArgs(opt StartOpts) []string {
	return append([]string{"--print"}, pi{}.InteractiveArgs(opt)...)
}
func (pi) ResumeCommand(id string) string {
	if strings.TrimSpace(id) == "" {
		return ""
	}
	return "pi --session " + id
}
func (pi) DetectConversationID(string) string { return "" }
func (pi) ConversationDir(string) string      { return "" }
