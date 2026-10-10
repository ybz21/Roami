package api

import "testing"

// 样本取自真实转录（~/.claude/projects 与 ~/.codex/sessions），字段名和嵌套层级照抄，
// 不是手编的——这两个解析器唯一的风险就是「上游换了字段名而我们不知道」。

func TestScanStatusClaude(t *testing.T) {
	st := cStatus{}
	// 改权限模式当场落一行（实测一份转录里有 16 条这样的行）
	st = scanStatus(`{"type":"permission-mode","permissionMode":"plan"}`, st)
	if st.Mode != "plan" {
		t.Fatalf("mode = %q, want plan", st.Mode)
	}
	// assistant 行带模型、推理档与 usage
	line := `{"type":"assistant","effort":"high","message":{"model":"claude-opus-5","usage":` +
		`{"input_tokens":2,"cache_creation_input_tokens":2634,"cache_read_input_tokens":269173,"output_tokens":723}}}`
	st = scanStatus(line, st)
	if st.Model != "claude-opus-5" {
		t.Errorf("model = %q", st.Model)
	}
	if st.Effort != "high" {
		t.Errorf("effort = %q", st.Effort)
	}
	// 上下文占用 = 新增 + 写缓存 + 读缓存（输出不算，它不占下一轮的输入窗口）
	if want := 2 + 2634 + 269173; st.Used != want {
		t.Errorf("used = %d, want %d", st.Used, want)
	}
	// 窗口取决于本机 ~/.claude/settings.json（这台机器就是 opus[1m] → 1M），
	// 所以这里只断言落在已知档位上，不把测试焊死在某台机器的配置上。
	if st.Window != defaultCtxWindow && st.Window != largeCtxWindow {
		t.Errorf("window = %d, want %d or %d", st.Window, defaultCtxWindow, largeCtxWindow)
	}
	// 后来的模式覆盖先前的
	st = scanStatus(`{"type":"permission-mode","permissionMode":"bypassPermissions"}`, st)
	if st.Mode != "bypassPermissions" {
		t.Errorf("mode = %q", st.Mode)
	}
	// 非状态行不该动任何字段
	before := st
	st = scanStatus(`{"type":"summary","summary":"x"}`, st)
	if st != before {
		t.Errorf("非状态行改了状态: %+v -> %+v", before, st)
	}
	// 坏行不能 panic，也不该清空已有状态
	st = scanStatus(`{not json`, st)
	if st != before {
		t.Errorf("坏行改了状态: %+v", st)
	}
}

func TestHasOneM(t *testing.T) {
	// 转录里的 message.model 被剥成了 "claude-opus-5"，据它判必然漏——
	// 真正带标记的是 ~/.claude/settings.json 的 model（形如 "opus[1m]"）。
	cases := map[string]bool{
		"opus[1m]":          true,
		"claude-opus-5[1m]": true,
		"claude-opus-5-1m":  true,
		"claude-opus-5":     false,
		"claude-sonnet-5":   false,
		"":                  false,
	}
	for model, want := range cases {
		if got := hasOneM(model); got != want {
			t.Errorf("hasOneM(%q) = %v, want %v", model, got, want)
		}
	}
}

func TestClaudeWindowFallsBackTo200k(t *testing.T) {
	// 转录 model 不带标记时至少不会崩；具体取值还取决于本机 settings.json，
	// 所以只断言落在已知档位上（前端另有 fitWindow 兜底升档，见 chat/status.ts）。
	got := claudeWindow("claude-opus-5")
	if got != defaultCtxWindow && got != largeCtxWindow {
		t.Errorf("claudeWindow = %d, want %d or %d", got, defaultCtxWindow, largeCtxWindow)
	}
	if claudeWindow("claude-opus-5[1m]") != largeCtxWindow {
		t.Errorf("带 [1m] 的必须给 1M")
	}
}

func TestScanCodexStatus(t *testing.T) {
	st := cStatus{}
	quota := 0.0
	turn := `{"type":"turn_context","payload":{"model":"gpt-5.6-sol","approval_policy":"never",` +
		`"sandbox_policy":{"type":"danger-full-access"},` +
		`"collaboration_mode":{"mode":"default","settings":{"reasoning_effort":"high"}}}}`
	st = scanCodexStatus(turn, st, &quota)
	if st.Model != "gpt-5.6-sol" || st.Effort != "high" || st.Mode != "default" {
		t.Fatalf("turn_context 解析错: %+v", st)
	}

	// token_count 直接给窗口，不用按模型 id 猜
	tok := `{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":` +
		`{"total_tokens":158263367},"last_token_usage":{"total_tokens":16543},"model_context_window":258400},` +
		`"rate_limits":{"primary":{"used_percent":44.0}}}}`
	st = scanCodexStatus(tok, st, &quota)
	if st.Used != 16543 || st.Window != 258400 {
		t.Errorf("token_count 解析错: used=%d window=%d", st.Used, st.Window)
	}
	if quota != 44.0 {
		t.Errorf("quota = %v, want 44", quota)
	}
	// 累计 token 可远超上下文窗口；缺少本轮用量时保留上一轮值。
	st = scanCodexStatus(`{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"total_tokens":999999999}}}}`, st, &quota)
	if st.Used != 16543 {
		t.Errorf("累计用量不应覆盖本轮上下文: used=%d", st.Used)
	}

	// 没有协作模式时退回沙箱策略——「它现在能不能动我的盘」比模式名更要紧
	st2 := scanCodexStatus(`{"type":"turn_context","payload":{"sandbox_policy":{"type":"read-only"}}}`, cStatus{}, &quota)
	if st2.Mode != "read-only" {
		t.Errorf("回退沙箱策略失败: %q", st2.Mode)
	}

	// 别的 event_msg（本文件里最常见的一类）不该动状态
	before := st
	st = scanCodexStatus(`{"type":"event_msg","payload":{"type":"agent_message","message":"hi"}}`, st, &quota)
	if st != before {
		t.Errorf("无关事件改了状态: %+v -> %+v", before, st)
	}
}

func TestClipUsesSentinel(t *testing.T) {
	long := make([]byte, blockCap+10)
	for i := range long {
		long[i] = 'x'
	}
	out := clip(string(long))
	// 截断标记必须是哨兵而非中文：它会直接进 API 响应，文案由前端出译文
	if got := out[len(out)-len(clipMark):]; got != clipMark {
		t.Errorf("截断标记 = %q, want %q", got, clipMark)
	}
	if len(out) != blockCap+len(clipMark) {
		t.Errorf("截断长度 = %d", len(out))
	}
	if s := "短文本"; clip(s) != s {
		t.Errorf("没超长的不该动")
	}
}
