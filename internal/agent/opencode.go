package agent

func init() { Register(opencode{}) }

type opencode struct{}

func (opencode) Kind() string             { return "opencode" }
func (opencode) DisplayName() string      { return "OpenCode" }
func (opencode) Bin() string              { return "opencode" }
func (opencode) PinsConversationID() bool { return false }
func (opencode) OneShotPromptArg() bool   { return true }
func (opencode) InteractiveArgs(opt StartOpts) []string {
	var args []string
	if opt.Model != "" {
		args = append(args, "--model", opt.Model)
	}
	args = append(args, openCodePermissionArgs(opt.Permission)...)
	return append(args, "--prompt")
}
func (opencode) OneShotArgs(opt StartOpts) []string {
	args := []string{"run"}
	if opt.Model != "" {
		args = append(args, "--model", opt.Model)
	}
	return append(args, openCodePermissionArgs(opt.Permission)...)
}

func openCodePermissionArgs(permission string) []string {
	if permission == "auto" || permission == "dangerously-skip-permissions" {
		return []string{"--auto"}
	}
	return nil
}

func (opencode) ResumeCommand(string) string        { return "" }
func (opencode) DetectConversationID(string) string { return "" }
func (opencode) ConversationDir(string) string      { return "" }
