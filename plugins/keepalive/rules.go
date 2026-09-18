package keepalive

import "strings"

// 守护语不是一句话,是一张有序规则表:每条回答「屏幕上出现这个 → 就说这句」,
// 最后一条兜底。从上往下匹配,命中即用。
//
// 为什么非得分叉:Agent 停住有三种,而它们长得一模一样(会话还在、进程还在、
// 屏幕不动)。其中最贵的一种是**断在半路**——`API Error: Connection lost
// mid-response`。对它说「继续」,Claude/Codex 往往理解成「继续这个任务」而不是
// 「接上刚才那句」,于是重新开一遍思路;如果刚才已经改了半个仓库,第二遍还会
// 跟第一遍打架。

// Rule 是一条守护语规则。
type Rule struct {
	// Match 是屏幕末尾 CaptureLines 行里要找的子串;多个用 | 分隔,任一命中即算命中。
	// 空串 + AtNth==0 = 兜底条(永远命中,必须排在最后)。
	//
	// **故意不给正则**:规则表是给人填的,填错一个正则的代价是「这条永远不命中」,
	// 而且没人看得出来。
	Match string `json:"match"`
	// AtNth > 0 时这条不看屏幕,只在「这是第 N 次催」时命中。
	// 屏幕上没有任何字样能表示「它该回头检查了」,那条规则只能挂在次数上。
	AtNth   int    `json:"atNth,omitempty"`
	Prompt  string `json:"prompt"`
	Enabled bool   `json:"enabled"`
}

// IsFallback 兜底条:删不掉、永远排最后、只能改它说什么。
func (r Rule) IsFallback() bool { return strings.TrimSpace(r.Match) == "" && r.AtNth <= 0 }

// maxRules 规则表上限。一张要从上往下读的表,超过这个数就没人读得完了。
const maxRules = 20

// DefaultRules 是第一次打开时装好的三条。
func DefaultRules() []Rule {
	return []Rule{
		{
			Match:   "Connection lost mid-response|API Error|Request timed out|fetch failed",
			Prompt:  "刚才那次请求断在半路了，从断掉的地方接着说，别重头再来一遍",
			Enabled: true,
		},
		{
			AtNth:   2,
			Prompt:  "先别往下写了，回头自查一遍：跑一遍构建和测试，把结果贴出来",
			Enabled: false,
		},
		{Match: "", Prompt: DefaultPrompt, Enabled: true},
	}
}

// NormalizeRules 收拾一张规则表,让它一定是「若干条普通规则 + 结尾恰好一条兜底」。
//
// 这层不是防御性洁癖:兜底条要是丢了或跑到中间,整张表的语义就变了
// (跑到中间 = 它后面的规则永远不命中)。面板那边再怎么拖,存进来都会被这里摆正。
func NormalizeRules(rs []Rule) []Rule {
	out := make([]Rule, 0, len(rs)+1)
	var fallback *Rule
	for i := range rs {
		r := rs[i]
		r.Match, r.Prompt = strings.TrimSpace(r.Match), TrimPrompt(r.Prompt)
		if r.AtNth < 0 {
			r.AtNth = 0
		}
		if r.IsFallback() {
			// 多来几条兜底只认第一条,其余丢掉——它们本来就永远轮不到。
			if fallback == nil {
				fallback = &r
			}
			continue
		}
		if r.Prompt == "" {
			continue // 不说话的规则等于没有
		}
		out = append(out, r)
	}
	if len(out) > maxRules-1 {
		out = out[:maxRules-1]
	}
	if fallback == nil {
		fallback = &Rule{Prompt: DefaultPrompt, Enabled: true}
	}
	if fallback.Prompt == "" {
		fallback.Prompt = DefaultPrompt
	}
	fallback.Enabled = true // 兜底条不许关:关了就等于「有时候一句话都不说」
	return append(out, *fallback)
}

// PickPrompt 挑这一次该说哪句。screen 是屏幕末尾那几行,nth 是这将是第几次催(1 起)。
// 返回命中的规则下标(兜底也算一条,-1 表示表是空的 → 用 settings 里的兜底语)。
func PickPrompt(rs []Rule, screen string, nth int, fallback string) (string, int) {
	tail := strings.ToLower(screen)
	for i, r := range rs {
		if !r.Enabled {
			continue
		}
		switch {
		case r.AtNth > 0:
			if nth != r.AtNth {
				continue
			}
		case r.IsFallback():
			// 兜底条永远命中,靠它排在最后来保证「先让别人试」
		default:
			if !matchAny(tail, r.Match) {
				continue
			}
		}
		if p := TrimPrompt(r.Prompt); p != "" {
			return p, i
		}
	}
	return TrimPrompt(fallback), -1
}

// matchAny 大小写不敏感地找 | 分隔的任一关键词。
func matchAny(lowerTail, match string) bool {
	for _, kw := range strings.Split(match, "|") {
		kw = strings.ToLower(strings.TrimSpace(kw))
		if kw != "" && strings.Contains(lowerTail, kw) {
			return true
		}
	}
	return false
}

// ruleView 是给面板的规则视图(字段名与 Rule 的 json tag 一致,外加一个
// fallback 标志——面板据此把最后那条画成不可删不可拖)。
func ruleView(r Rule) map[string]any {
	return map[string]any{
		"match": r.Match, "atNth": r.AtNth, "prompt": r.Prompt,
		"enabled": r.Enabled, "fallback": r.IsFallback(),
	}
}
