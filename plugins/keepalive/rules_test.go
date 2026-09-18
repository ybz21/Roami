package keepalive

import "testing"

// 规则表存在的理由只有一个：对「断在半路」的会话说「继续」，它会**重头再跑一遍**。
// 所以这一条必须比兜底先命中。
func TestDroppedRequestBeatsFallback(t *testing.T) {
	screen := "· Synthesizing…\nAPI Error: Connection lost mid-response\n"
	got, i := PickPrompt(DefaultRules(), screen, 1, DefaultPrompt)
	if i != 0 {
		t.Fatalf("断线那条没命中，命中的是第 %d 条", i)
	}
	if got == DefaultPrompt {
		t.Fatalf("断线会话拿到了兜底语: %q", got)
	}
}

func TestFallbackWhenNothingMatches(t *testing.T) {
	got, i := PickPrompt(DefaultRules(), "一切正常，等待输入\n", 1, DefaultPrompt)
	if got != DefaultPrompt {
		t.Fatalf("没命中就该用兜底语，得到 %q", got)
	}
	if i != len(DefaultRules())-1 {
		t.Fatalf("兜底条应该是最后一条，命中了第 %d 条", i)
	}
}

func TestMatchIsCaseInsensitiveAndOrSeparated(t *testing.T) {
	rs := NormalizeRules([]Rule{
		{Match: "foo|Request Timed Out", Prompt: "断了", Enabled: true},
		{Prompt: "兜底", Enabled: true},
	})
	if got, _ := PickPrompt(rs, "...request timed OUT...", 1, "x"); got != "断了" {
		t.Fatalf("大小写不敏感的子串没匹配上: %q", got)
	}
	if got, _ := PickPrompt(rs, "没有关键词", 1, "x"); got != "兜底" {
		t.Fatalf("不该命中却命中了: %q", got)
	}
}

// 「回头自查」那条挂在次数上，不看屏幕——屏幕上没有任何字样能表示「它该检查了」。
func TestAtNthRuleIgnoresScreen(t *testing.T) {
	rs := NormalizeRules([]Rule{
		{AtNth: 2, Prompt: "回头自查", Enabled: true},
		{Prompt: "兜底", Enabled: true},
	})
	if got, _ := PickPrompt(rs, "随便什么屏幕", 1, "x"); got != "兜底" {
		t.Fatalf("第 1 次不该命中 atNth=2: %q", got)
	}
	if got, _ := PickPrompt(rs, "随便什么屏幕", 2, "x"); got != "回头自查" {
		t.Fatalf("第 2 次该命中 atNth=2: %q", got)
	}
	if got, _ := PickPrompt(rs, "随便什么屏幕", 3, "x"); got != "兜底" {
		t.Fatalf("第 3 次不该再命中: %q", got)
	}
}

func TestDisabledRuleIsSkipped(t *testing.T) {
	rs := DefaultRules() // 第二条（回头自查）默认是关的
	if got, _ := PickPrompt(rs, "任意", 2, DefaultPrompt); got != DefaultPrompt {
		t.Fatalf("关掉的规则仍然命中了: %q", got)
	}
}

// 兜底条要是丢了或跑到中间，整张表的语义就变了（跑到中间 = 它后面的永远不命中）。
func TestNormalizeAlwaysEndsWithExactlyOneFallback(t *testing.T) {
	cases := [][]Rule{
		{{Prompt: "兜底A", Enabled: true}, {Match: "x", Prompt: "普通", Enabled: true}}, // 兜底在前
		{{Match: "x", Prompt: "普通", Enabled: true}},                                 // 根本没有兜底
		{{Prompt: "兜底A", Enabled: true}, {Prompt: "兜底B", Enabled: true}},            // 两条兜底
	}
	for i, in := range cases {
		out := NormalizeRules(in)
		if !out[len(out)-1].IsFallback() {
			t.Fatalf("[%d] 最后一条不是兜底: %+v", i, out)
		}
		n := 0
		for _, r := range out {
			if r.IsFallback() {
				n++
			}
		}
		if n != 1 {
			t.Fatalf("[%d] 兜底条有 %d 个，应该恰好 1 个", i, n)
		}
	}
}

// 兜底条不许关：关了就等于「有时候一句话都不说」，而那正是这个插件唯一的职责。
func TestFallbackCannotBeDisabledOrEmptied(t *testing.T) {
	out := NormalizeRules([]Rule{{Prompt: "", Enabled: false}})
	last := out[len(out)-1]
	if !last.Enabled {
		t.Fatal("兜底条被关掉了")
	}
	if last.Prompt != DefaultPrompt {
		t.Fatalf("兜底条空了没补回默认语: %q", last.Prompt)
	}
}

func TestNormalizeDropsSilentRulesAndFlattens(t *testing.T) {
	out := NormalizeRules([]Rule{
		{Match: "x", Prompt: "   ", Enabled: true},        // 不说话的规则等于没有
		{Match: " y ", Prompt: "第一行\n第二行", Enabled: true}, // 换行折平（TUI 里换行即提交）
		{Prompt: DefaultPrompt, Enabled: true},
	})
	if len(out) != 2 {
		t.Fatalf("空 prompt 的规则没被丢掉: %+v", out)
	}
	if out[0].Match != "y" || out[0].Prompt != "第一行 第二行" {
		t.Fatalf("没规整: %+v", out[0])
	}
}

func TestNormalizeCapsTableSize(t *testing.T) {
	in := make([]Rule, 0, 50)
	for i := 0; i < 50; i++ {
		in = append(in, Rule{Match: "k", Prompt: "p", Enabled: true})
	}
	if got := len(NormalizeRules(in)); got != maxRules {
		t.Fatalf("规则表没封顶: %d", got)
	}
}

// 默认兜底语不是「继续」——一句「继续」不给已经干完的 Agent 留台阶，
// 它会去找点事做，换来一次计划外的改动。
func TestDefaultFallbackIsNotJustContinue(t *testing.T) {
	last := DefaultRules()[len(DefaultRules())-1]
	if !last.IsFallback() {
		t.Fatal("默认表的最后一条不是兜底")
	}
	if last.Prompt == "继续" {
		t.Fatal("默认兜底语退回成了「继续」")
	}
	if last.Prompt != DefaultPrompt {
		t.Fatalf("默认兜底语该等于 DefaultPrompt: %q", last.Prompt)
	}
}
