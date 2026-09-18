package keepalive

import (
	"crypto/sha1"
	"encoding/hex"
	"strings"
)

// Settings 是全局默认。每条守护可以各自覆盖前三项,不填就跟着这里走。
type Settings struct {
	// Prompt 是兜底守护语——规则表里哪条都不命中时说的那句(见 rules.go)。
	Prompt string `json:"prompt"`
	// IdleMin:屏幕多少分钟没有任何变化,才算「它停住了」。
	IdleMin int `json:"idleMin"`
	// EveryMin:同一个会话两次催促之间至少隔这么久,防止连珠炮。
	EveryMin int `json:"everyMin"`
	// MaxQuiet:连着催这么多次都没换来真正的干活,就自动停手并发通知。
	// 0 = 不停手(明知会话是个裸 shell 也要一直催的,自己负责)。
	MaxQuiet int `json:"maxQuiet"`
}

// DefaultPrompt 是默认兜底守护语。
//
// **不是「继续」**:一句「继续」不给 Agent 留台阶——真干完了的它会去找点事做,
// 翻出个无关的改进、再重构一遍刚写好的东西;你本来只想确认它还活着,结果换来
// 一次计划外的改动。先问后推这句则是干完了就回一句交代,没干完才接着干。
const DefaultPrompt = "你是不是已经完成了你的任务？没有完成，那么继续。"

// 默认值。间隔取 30 分钟、安静阈值取 10 分钟:Agent 停下来等人的典型场景是
// 「问了个问题就不动了」,10 分钟足够把「正在想」和「真停了」分开;而 30 分钟
// 的最小间隔保证就算判断错了,一小时里也最多打扰它两次。
const (
	defIdleMin  = 10
	defEveryMin = 30
	defMaxQuiet = 3

	maxIdleMin  = 24 * 60
	maxEveryMin = 24 * 60
	maxMaxQuiet = 50
	// MaxPromptLen 守护语长度上限(按 rune 数)。它经 tmux paste-buffer 打进会话,
	// 是「一句话」不是一篇 prompt;真要发长文请用定时任务插件拉 Agent。
	MaxPromptLen = 500
	// CaptureLines 每轮抓多少行屏幕:指纹和规则匹配共用这一份。
	// 往上翻整屏会把半小时前的一次报错重新认成「刚断线」。
	CaptureLines = 40
)

// DefaultSettings 是一份全新的默认设置。
//
// 必须有这么个构造器,不能靠 Normalized 把零值填成默认:MaxQuiet 的 0 是有含义的
// (「永不自动停手」),分不清「没配过」和「配成了 0」。读设置时从这份出发再把存下来
// 的字段盖上去(json.Unmarshal 到预填结构体上,缺的键保持原值),两种 0 就分开了。
func DefaultSettings() Settings {
	return Settings{Prompt: DefaultPrompt, IdleMin: defIdleMin, EveryMin: defEveryMin, MaxQuiet: defMaxQuiet}
}

// Normalized 填默认值并把越界的夹回合法区间。**存进去之前就规范化**:
// 面板显示的和循环实际用的必须是同一份,否则用户看到 0 分钟、循环按 10 分钟跑。
func (s Settings) Normalized() Settings {
	out := s
	out.Prompt = TrimPrompt(out.Prompt)
	if out.Prompt == "" {
		out.Prompt = DefaultPrompt
	}
	out.IdleMin = clamp(out.IdleMin, defIdleMin, 1, maxIdleMin)
	out.EveryMin = clamp(out.EveryMin, defEveryMin, 1, maxEveryMin)
	if out.MaxQuiet < 0 {
		out.MaxQuiet = 0
	}
	if out.MaxQuiet > maxMaxQuiet {
		out.MaxQuiet = maxMaxQuiet
	}
	return out
}

// TrimPrompt 规整一句守护语:换行折成空格并截到上限。
//
// 折换行不是洁癖:守护语经 paste-buffer 打进 TUI,而 Claude/Codex 的输入框里
// **换行即提交**,多行文本会被拆成好几次输入(宿主的 session.send 也是这么折的)。
func TrimPrompt(s string) string {
	s = strings.TrimSpace(strings.ReplaceAll(strings.ReplaceAll(s, "\r", " "), "\n", " "))
	if r := []rune(s); len(r) > MaxPromptLen {
		s = strings.TrimSpace(string(r[:MaxPromptLen]))
	}
	return s
}

func clamp(v, def, lo, hi int) int {
	if v <= 0 {
		return def
	}
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// Guard 是一条守护。主键是**会话 id**而不是展示名:改名不该让守护失效,
// 而 id 由时间戳派生、永不复用,会话没了这条也就永远不会再匹配上。
//
// 没有「默认开」这回事:守护表一开始是空的,每一行都得有人亲手打开过
// ——每一条都会替用户花钱、往他的会话里写东西。
type Guard struct {
	Session string `json:"session"`
	Label   string `json:"label"` // 展示名快照,只为显示
	Enabled bool   `json:"enabled"`

	// 逐会话覆盖(零值=跟随全局)
	Prompt   string `json:"prompt,omitempty"`
	IdleMin  int    `json:"idleMin,omitempty"`
	EveryMin int    `json:"everyMin,omitempty"`

	// ── 运行态 ──
	Hash       string `json:"hash,omitempty"`       // 上一轮看到的屏幕指纹
	QuietSince int64  `json:"quietSince,omitempty"` // 从这一刻起屏幕没再变过
	LastSent   int64  `json:"lastSent,omitempty"`
	Sends      int    `json:"sends,omitempty"`
	Streak     int    `json:"streak,omitempty"`    // 连着催了几次都没换来真干活
	Responded  bool   `json:"responded,omitempty"` // 上次催完之后,它真的动起来过
	StoppedAt  int64  `json:"stoppedAt,omitempty"` // 自动停手的时刻(0=没停过)
}

// Effective 把逐会话覆盖并进全局默认,得到这条守护实际生效的参数。
func (g Guard) Effective(s Settings) Settings {
	out := s
	if TrimPrompt(g.Prompt) != "" {
		out.Prompt = g.Prompt
	}
	if g.IdleMin > 0 {
		out.IdleMin = g.IdleMin
	}
	if g.EveryMin > 0 {
		out.EveryMin = g.EveryMin
	}
	return out.Normalized()
}

// graceSec 是「这次屏幕变化算不算它真的动起来了」的分界。
//
// 催一句之后屏幕**必然**会变——我们打进去的那行字自己就在屏幕上。所以刚发完
// 那一小会儿的变化一律不算数,只有过了这道坎还在变的,才是它真的接着干了。
// 取 60 秒:比巡检周期(30s)长一轮有余,又短到不会把「答了一句就完事」的
// 正常响应误判成没反应。
const graceSec = 60

// Probe 是一轮巡检里从宿主拿到的「这个会话此刻什么样」。
type Probe struct {
	Alive bool
	Hash  string // 屏幕末尾若干行的指纹;取不到时为空串
}

// Decision 是 Step 对一条守护的处置。Guard 是更新后的状态,调用方原样写回。
type Decision struct {
	Guard Guard
	// Send 为真时该发一句;Stop 为真时该停手(此时 Send 必为假)。
	Send bool
	Stop bool
	// Nth 是这一次是第几次催(1 起),供规则表按「催到第 N 次」分叉。
	Nth int
	// QuietSec 是发的时候它已经安静了多久,只在 Send 时有意义(记账用)。
	QuietSec int64
}

// Step 是守护的全部判断逻辑,纯函数——真正难的不是发消息,是「什么时候不该发」。
//
// 判「还动不动」看屏幕指纹而不是 tmux 的 session_activity:后者在我们自己
// paste 那句话的时候也会跳,拿它判断等于自己跟自己确认「它动了」。
func Step(g Guard, p Probe, s Settings, now int64) Decision {
	eff := g.Effective(s)
	d := Decision{Guard: g}
	// 会话不在、或者这一轮压根没看到屏幕(capture 失败),都属于「看不见」:
	// 什么都不判断也什么都不改。把看不见当成安静,就会对着一个读不到的会话
	// 一直催。
	if !g.Enabled || !p.Alive || p.Hash == "" {
		return d
	}
	// 屏幕变了:重新开始计安静时间。若这变化发生在宽限期之外,说明上一次催
	// 确实换来了干活,连败计数清零。
	if p.Hash != d.Guard.Hash {
		if d.Guard.LastSent > 0 && now-d.Guard.LastSent > graceSec {
			d.Guard.Responded = true
		}
		d.Guard.Hash = p.Hash
		d.Guard.QuietSince = now
		return d
	}
	quiet := now - d.Guard.QuietSince
	if quiet < int64(eff.IdleMin)*60 {
		return d
	}
	if d.Guard.LastSent > 0 && now-d.Guard.LastSent < int64(eff.EveryMin)*60 {
		return d
	}
	if d.Guard.Responded {
		d.Guard.Streak = 0
		d.Guard.Responded = false
	}
	if eff.MaxQuiet > 0 && d.Guard.Streak >= eff.MaxQuiet {
		d.Guard.Enabled = false
		d.Guard.StoppedAt = now
		d.Stop = true
		return d
	}
	d.Send = true
	d.QuietSec = quiet
	d.Guard.Sends++
	d.Nth = d.Guard.Sends
	d.Guard.Streak++
	d.Guard.LastSent = now
	// 刚打进去的那句话马上就会改变屏幕,把安静起点推到此刻,免得下一轮
	// 因为「指纹变了」而重置——那会把一次正常的催促记成一次响应。
	d.Guard.QuietSince = now
	return d
}

// ScreenHash 把一屏内容压成指纹。会话一直在滚动输出时这个值每轮都不同,
// 停下来等人时则一动不动——正是我们要的「还动不动」。
func ScreenHash(screen string) string {
	trimmed := strings.TrimRight(screen, " \t\n")
	if trimmed == "" {
		return ""
	}
	sum := sha1.Sum([]byte(trimmed))
	return hex.EncodeToString(sum[:8])
}
