package agent

import "strings"
import "testing"

// 假的一型，只实现接口、不碰任何既有代码 —— 验证「新增一型」的成本。
type gemini struct{}

func (gemini) Kind() string             { return "gemini" }
func (gemini) DisplayName() string      { return "Gemini CLI" }
func (gemini) Bin() string              { return "gemini" }
func (gemini) PinsConversationID() bool { return true }
func (gemini) InteractiveArgs(o StartOpts) []string {
	if o.ConvID != "" {
		return []string{"--chat", o.ConvID}
	}
	return nil
}
func (gemini) OneShotArgs(o StartOpts) []string { return []string{"--stdin"} }
func (g gemini) ResumeCommand(c string) string {
	if c == "" {
		return ""
	}
	return g.Bin() + " --chat " + c
}
func (gemini) DetectConversationID(string) string { return "" }
func (gemini) ConversationDir(string) string      { return "" }

func TestNewKindNeedsNoChangesElsewhere(t *testing.T) {
	Register(gemini{})
	defer func() { mu.Lock(); delete(registry, "gemini"); mu.Unlock() }()

	if a := Get("gemini"); a == nil {
		t.Fatal("注册完却取不到")
	}
	// 恢复这条路自动认得它
	if got := ResumeCommandFor("gemini", "C1"); got != "gemini --chat C1" {
		t.Errorf("恢复命令 = %q", got)
	}
	// 列表/校验这条路也认得
	found := false
	for _, k := range Kinds() {
		if k == "gemini" {
			found = true
		}
	}
	if !found {
		t.Error("Kinds() 里没有它，swarm 的 --kind 校验会拒绝它")
	}
	// 启动参数
	if got := strings.Join(Get("gemini").InteractiveArgs(StartOpts{ConvID: "X"}), " "); got != "--chat X" {
		t.Errorf("交互参数 = %q", got)
	}
}
