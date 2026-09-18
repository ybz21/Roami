package keepalive

import "testing"

// 守护真正难的不是发消息，是**什么时候不该发**。这一组全是「不该发」。

const min = int64(60)

func base() (Guard, Settings) {
	st := DefaultSettings().Normalized() // 安静 10 分钟 / 最快 30 分钟 / 连败 3 次停手
	g := Guard{Session: "2026-0918-1000-0001", Label: "干活的", Enabled: true}
	return g, st
}

// 屏幕在动 = 它还活着，无论安静计时器攒了多久。
func TestScreenMovingNeverNudges(t *testing.T) {
	g, st := base()
	g.Hash, g.QuietSince = "aaa", 1000
	d := Step(g, Probe{Alive: true, Hash: "bbb"}, st, 1000+99*min)
	if d.Send {
		t.Fatal("屏幕变了还催，等于打断正在干活的 Agent")
	}
	if d.Guard.QuietSince != 1000+99*min {
		t.Fatalf("屏幕一变就该重新计安静时间，得到 %d", d.Guard.QuietSince)
	}
}

// 「看不见」不等于「安静」：capture 失败的那一轮什么都不判断也什么都不改。
func TestBlindRoundChangesNothing(t *testing.T) {
	g, st := base()
	g.Hash, g.QuietSince = "aaa", 1000
	for _, p := range []Probe{
		{Alive: true, Hash: ""}, // 抓不到屏幕
		{Alive: false, Hash: "aaa"},
	} {
		d := Step(g, p, st, 1000+99*min)
		if d.Send || d.Stop {
			t.Fatalf("看不见还动手了: %+v", p)
		}
		if d.Guard != g {
			t.Fatalf("看不见的那一轮不该改状态: %+v", d.Guard)
		}
	}
}

// 没开守护的会话，安静到天荒地老也不碰。
func TestDisabledGuardIsNeverTouched(t *testing.T) {
	g, st := base()
	g.Enabled, g.Hash, g.QuietSince = false, "aaa", 1000
	if d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+99*min); d.Send {
		t.Fatal("开关是关的还催")
	}
}

// 安静没到阈值不催；到了才催。
func TestNudgesOnlyAfterIdleThreshold(t *testing.T) {
	g, st := base()
	g.Hash, g.QuietSince = "aaa", 1000
	if d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+9*min); d.Send {
		t.Fatal("安静 9 分钟就催，阈值是 10 分钟")
	}
	d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+10*min)
	if !d.Send {
		t.Fatal("安静够 10 分钟了还不催")
	}
	if d.Nth != 1 || d.Guard.Sends != 1 || d.Guard.Streak != 1 {
		t.Fatalf("第一次催的记账不对: %+v", d)
	}
	if d.Guard.QuietSince != 1000+10*min {
		t.Fatal("催完要把安静起点推到此刻，否则下一轮会把自己打的字当成它响应了")
	}
}

// 最小间隔是硬的：就算它一直安静，也不能连珠炮。
func TestMinIntervalHolds(t *testing.T) {
	g, st := base()
	g.Hash, g.QuietSince, g.LastSent, g.Sends, g.Streak = "aaa", 1000, 1000, 1, 1
	if d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+29*min); d.Send {
		t.Fatal("离上次催才 29 分钟就又催，最小间隔是 30 分钟")
	}
	if d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+31*min); !d.Send {
		t.Fatal("过了最小间隔还不催")
	}
}

// 宽限期内的屏幕变化是**我们自己打进去的那行字**，不算它响应了。
func TestOwnEchoIsNotAResponse(t *testing.T) {
	g, st := base()
	g.Hash, g.QuietSince, g.LastSent = "aaa", 1000, 1000
	d := Step(g, Probe{Alive: true, Hash: "echo"}, st, 1000+graceSec-1)
	if d.Guard.Responded {
		t.Fatal("刚发完就把自己的回显当成它动起来了")
	}
	d = Step(g, Probe{Alive: true, Hash: "real"}, st, 1000+graceSec+1)
	if !d.Guard.Responded {
		t.Fatal("过了宽限期的屏幕变化才是真响应，没认出来")
	}
}

// 连催到上限就停手，而且停手时**不再发**那一句。
func TestStopsAfterMaxQuiet(t *testing.T) {
	g, st := base()
	g.Hash, g.QuietSince, g.Streak, g.Sends = "aaa", 1000, 3, 3
	g.LastSent = 1000 - 99*min
	d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+10*min)
	if !d.Stop || d.Send {
		t.Fatalf("连败 3 次该停手且不再发: stop=%v send=%v", d.Stop, d.Send)
	}
	if d.Guard.Enabled || d.Guard.StoppedAt == 0 {
		t.Fatalf("停手要落到守护状态上: %+v", d.Guard)
	}
}

// 它真干过活，旧账就一笔勾销——不该因为半天前的三次没反应把人停了。
func TestRespondingClearsTheStreak(t *testing.T) {
	g, st := base()
	g.Hash, g.QuietSince, g.Streak, g.Sends, g.Responded = "aaa", 1000, 3, 3, true
	g.LastSent = 1000 - 99*min
	d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+10*min)
	if d.Stop {
		t.Fatal("中间它响应过，不该停手")
	}
	if !d.Send || d.Guard.Streak != 1 {
		t.Fatalf("清零后应从 1 重新数: send=%v streak=%d", d.Send, d.Guard.Streak)
	}
}

// maxQuiet=0 = 明知道是裸 shell 也要一直催，自己负责。
func TestMaxQuietZeroNeverStops(t *testing.T) {
	g, st := base()
	st.MaxQuiet = 0
	g.Hash, g.QuietSince, g.Streak, g.Sends = "aaa", 1000, 99, 99
	g.LastSent = 1000 - 99*min
	if d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+10*min); d.Stop || !d.Send {
		t.Fatalf("maxQuiet=0 就不该停手: stop=%v send=%v", d.Stop, d.Send)
	}
}

// 逐会话覆盖盖得住全局，留空的那几项仍跟着全局。
func TestPerGuardOverride(t *testing.T) {
	g, st := base()
	g.IdleMin, g.Prompt = 2, "你那边怎么样了？"
	eff := g.Effective(st)
	if eff.IdleMin != 2 || eff.EveryMin != 30 || eff.Prompt != "你那边怎么样了？" {
		t.Fatalf("覆盖合并不对: %+v", eff)
	}
	g.Hash, g.QuietSince = "aaa", 1000
	if d := Step(g, Probe{Alive: true, Hash: "aaa"}, st, 1000+2*min); !d.Send {
		t.Fatal("这条守护自己说了安静 2 分钟就催")
	}
}

func TestSettingsNormalize(t *testing.T) {
	// 越界夹回区间，0 视作没填
	s := Settings{IdleMin: -5, EveryMin: 0, MaxQuiet: -1}.Normalized()
	if s.IdleMin != defIdleMin || s.EveryMin != defEveryMin || s.MaxQuiet != 0 {
		t.Fatalf("默认值没填对: %+v", s)
	}
	if s.Prompt != DefaultPrompt {
		t.Fatalf("兜底守护语该是「先问后推」那句，得到 %q", s.Prompt)
	}
	// MaxQuiet 的 0 有含义（永不停手），所以「没配过」只能靠构造器表达
	if d := DefaultSettings(); d.MaxQuiet != defMaxQuiet {
		t.Fatalf("全新设置该带上停手线: %+v", d)
	}
	if got := (Settings{IdleMin: 99999}).Normalized().IdleMin; got != maxIdleMin {
		t.Fatalf("上限没夹住: %d", got)
	}
}

// 守护语经 paste-buffer 打进 TUI，而那里**换行即提交**——多行必须折成一行，
// 否则一句话会被拆成好几次输入。
func TestTrimPromptFlattensNewlines(t *testing.T) {
	if got := TrimPrompt("  第一行\n第二行\r\n第三行  "); got != "第一行 第二行  第三行" {
		t.Fatalf("换行没折平: %q", got)
	}
	long := make([]rune, MaxPromptLen+50)
	for i := range long {
		long[i] = '啊'
	}
	if got := len([]rune(TrimPrompt(string(long)))); got != MaxPromptLen {
		t.Fatalf("超长没截到上限: %d", got)
	}
}

func TestScreenHash(t *testing.T) {
	if ScreenHash("   \n\n") != "" {
		t.Fatal("空屏该给空指纹——那是「看不见」，不是「安静」")
	}
	if ScreenHash("a\n") != ScreenHash("a\n\n  ") {
		t.Fatal("末尾空白不该算屏幕变化：TUI 每帧的行尾填充长度都可能不同")
	}
	if ScreenHash("a") == ScreenHash("b") {
		t.Fatal("内容不同指纹却一样")
	}
}
