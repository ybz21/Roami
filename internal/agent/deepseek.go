package agent

func init() { Register(deepseek{}) }

// The shipped headless profile reads stdin and prints final text on stdout.
type deepseek struct{}

func (deepseek) Kind() string             { return "deepseek" }
func (deepseek) DisplayName() string      { return "DeepSeek Harness" }
func (deepseek) Bin() string              { return "dsh" }
func (deepseek) PinsConversationID() bool { return false }
func (deepseek) InteractiveArgs(opt StartOpts) []string {
	args := []string{"--profile", "headless"}
	if opt.Permission == "auto" || opt.Permission == "dangerously-skip-permissions" {
		args = append(args, "--permission-mode", "danger-full-access")
	}
	return args
}
func (d deepseek) OneShotArgs(opt StartOpts) []string { return append(d.InteractiveArgs(opt), "-") }
func (deepseek) ResumeCommand(string) string          { return "" }
func (deepseek) DetectConversationID(string) string   { return "" }
func (deepseek) ConversationDir(string) string        { return "" }
func (deepseek) InstallPackage() Package {
	return Package{Name: "@deepseek-ai/dsh", Tag: "latest"}
}
func (deepseek) Descriptor() Descriptor {
	return Descriptor{SetupCommand: "dsh web", Command: "dsh --profile headless --permission-mode danger-full-access", Interactive: false}
}
