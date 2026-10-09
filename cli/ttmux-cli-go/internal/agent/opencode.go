package agent

func init() { Register(opencode{}) }

type opencode struct{}

func (opencode) Kind() string             { return "opencode" }
func (opencode) DisplayName() string      { return "OpenCode" }
func (opencode) Bin() string              { return "opencode" }
func (opencode) PinsConversationID() bool { return false }
func (opencode) OneShotPromptArg() bool   { return true }
func (opencode) InteractiveArgs(opt StartOpts) []string {
	if opt.Model != "" {
		return []string{"--model", opt.Model, "--prompt"}
	}
	return []string{"--prompt"}
}
func (opencode) OneShotArgs(opt StartOpts) []string {
	args := []string{"run"}
	if opt.Model != "" {
		args = append(args, "--model", opt.Model)
	}
	return args
}
func (opencode) ResumeCommand(string) string        { return "" }
func (opencode) DetectConversationID(string) string { return "" }
func (opencode) ConversationDir(string) string      { return "" }
