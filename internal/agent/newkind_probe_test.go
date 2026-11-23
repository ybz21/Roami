package agent

import "strings"
import "testing"

// 假的一型，只实现接口、不碰任何既有代码 —— 验证「新增一型」的成本。
type testHarness struct{}

func (testHarness) Kind() string             { return "test-harness" }
func (testHarness) DisplayName() string      { return "Test Harness" }
func (testHarness) Bin() string              { return "test-harness" }
func (testHarness) PinsConversationID() bool { return true }
func (testHarness) InteractiveArgs(o StartOpts) []string {
	if o.ConvID != "" {
		return []string{"--chat", o.ConvID}
	}
	return nil
}
func (testHarness) OneShotArgs(o StartOpts) []string { return []string{"--stdin"} }
func (g testHarness) ResumeCommand(c string) string {
	if c == "" {
		return ""
	}
	return g.Bin() + " --chat " + c
}
func (testHarness) DetectConversationID(string) string { return "" }
func (testHarness) ConversationDir(string) string      { return "" }

func TestNewKindNeedsNoChangesElsewhere(t *testing.T) {
	Register(testHarness{})
	defer func() { mu.Lock(); delete(registry, "test-harness"); mu.Unlock() }()

	if a := Get("test-harness"); a == nil {
		t.Fatal("注册完却取不到")
	}
	if d := Describe(Get("test-harness")); d.Kind != "test-harness" || d.DisplayName != "Test Harness" || d.Command != "test-harness" || !d.Interactive || d.Models || d.CanInstall {
		t.Fatalf("new registration missing metadata: %+v", d)
	}
	// 恢复这条路自动认得它
	if got := ResumeCommandFor("test-harness", "C1"); got != "test-harness --chat C1" {
		t.Errorf("恢复命令 = %q", got)
	}
	// 列表/校验这条路也认得
	found := false
	for _, k := range Kinds() {
		if k == "test-harness" {
			found = true
		}
	}
	if !found {
		t.Error("Kinds() 里没有它，swarm 的 --kind 校验会拒绝它")
	}
	// 启动参数
	if got := strings.Join(Get("test-harness").InteractiveArgs(StartOpts{ConvID: "X"}), " "); got != "--chat X" {
		t.Errorf("交互参数 = %q", got)
	}
}
