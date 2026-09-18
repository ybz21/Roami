package keepalive

import (
	"encoding/json"
	"fmt"
	"strings"

	"ttmux-cli-go/pkg/plugin/sdk"
)

// 插件私有 KV 里的几张表。整表一个 JSON、读改写(同 roam.cron 的存法):
// 守护表最多几十行,为它上一套增量写没有意义。
//
// 为什么不走 manifest 的 configFields:ctx.Config 是**激活时注入**的快照,
// 常驻循环一跑 24 小时,中途改了守护语它看不见,得重启循环才生效——而用户
// 不会知道要重启什么。放 storage 则每轮重读,改完下一轮就生效。
const (
	guardsKey   = "guards"
	settingsKey = "settings"
	rulesKey    = "rules"
	historyKey  = "history"
	// tickKey 记下上一次巡检的时刻。面板拿它回答那个最要紧的问题——
	// 「这东西到底在不在跑」:表里配得再漂亮,没人巡检就一条都不会发。
	tickKey = "tick"
	// wantedKey 是插件对宿主举的手:「我现在有活要干,请让常驻循环起来」。
	// plugind 只读这一个键(见 internal/plugin/daemon.go),不去解析守护表——
	// 宿主不该知道插件的数据结构长什么样。
	wantedKey = "wanted"
)

// historyCap 发送记录保留多少条。翻记录是为了回答「刚才那次到底发了没」,
// 不是做审计长河;真正的审计在宿主的 audit 里。
const historyCap = 200

// Send 是一次发送记录。
type Send struct {
	At       int64  `json:"at"`
	Session  string `json:"session"`
	Label    string `json:"label"`
	Prompt   string `json:"prompt"`
	Trigger  string `json:"trigger"` // watch=巡检发的 | manual=面板上点的
	Rule     int    `json:"rule"`    // 命中的规则下标,-1=没有规则表用了兜底语
	Nth      int    `json:"nth,omitempty"`
	QuietSec int64  `json:"quietSec,omitempty"`
	Stopped  bool   `json:"stopped,omitempty"` // 这一条记的是「自动停手」
	Error    string `json:"error,omitempty"`
}

func loadGuards(ctx *sdk.Ctx) ([]Guard, error) {
	raw, err := ctx.StorageGet(guardsKey)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(raw) == "" {
		return nil, nil
	}
	var gs []Guard
	if err := json.Unmarshal([]byte(raw), &gs); err != nil {
		return nil, fmt.Errorf("守护表损坏,无法解析: %w", err)
	}
	return gs, nil
}

// saveGuards 落守护表,并顺手把 wanted 这面旗子对齐。两件事必须同一处做:
// 分开写就一定会出现「表里还有守护、旗子已经落下」——循环不起来,面板上却
// 一切正常,这种错没人查得出来。
func saveGuards(ctx *sdk.Ctx, gs []Guard) error {
	b, err := json.Marshal(gs)
	if err != nil {
		return err
	}
	if err := ctx.StorageSet(guardsKey, string(b)); err != nil {
		return err
	}
	flag := ""
	if CountEnabled(gs) > 0 {
		flag = "1"
	}
	return ctx.StorageSet(wantedKey, flag)
}

// CountEnabled 有几条守护是开着的。
func CountEnabled(gs []Guard) int {
	n := 0
	for _, g := range gs {
		if g.Enabled {
			n++
		}
	}
	return n
}

func loadSettings(ctx *sdk.Ctx) (Settings, error) {
	raw, err := ctx.StorageGet(settingsKey)
	if err != nil {
		return DefaultSettings(), err
	}
	// 从默认值出发再盖上存下来的字段:缺的键保持默认,而不是变成零值
	// (MaxQuiet 的 0 是「永不停手」,不是「没配过」)。
	s := DefaultSettings()
	if strings.TrimSpace(raw) != "" {
		// 设置读不出来时退回默认值而不是报错:守护的价值在于它一直在跑,
		// 不该因为一行坏 JSON 就整个停摆。
		if json.Unmarshal([]byte(raw), &s) != nil {
			s = DefaultSettings()
		}
	}
	return s.Normalized(), nil
}

func saveSettings(ctx *sdk.Ctx, s Settings) error {
	b, err := json.Marshal(s.Normalized())
	if err != nil {
		return err
	}
	return ctx.StorageSet(settingsKey, string(b))
}

// loadRules 读规则表;从没配过就装默认那三条(同理由:坏数据也退回默认)。
func loadRules(ctx *sdk.Ctx) []Rule {
	raw, err := ctx.StorageGet(rulesKey)
	if err != nil || strings.TrimSpace(raw) == "" {
		return DefaultRules()
	}
	var rs []Rule
	if json.Unmarshal([]byte(raw), &rs) != nil || len(rs) == 0 {
		return DefaultRules()
	}
	return NormalizeRules(rs)
}

func saveRules(ctx *sdk.Ctx, rs []Rule) error {
	b, err := json.Marshal(NormalizeRules(rs))
	if err != nil {
		return err
	}
	return ctx.StorageSet(rulesKey, string(b))
}

func loadHistory(ctx *sdk.Ctx) []Send {
	raw, err := ctx.StorageGet(historyKey)
	if err != nil || strings.TrimSpace(raw) == "" {
		return nil
	}
	var hs []Send
	if json.Unmarshal([]byte(raw), &hs) != nil {
		return nil
	}
	return hs
}

// record 把一次发送记进环形记录(新的在前)。记不进去不影响这次发送的结果,
// 它只是给人看的。
func record(ctx *sdk.Ctx, s Send) {
	hs := append([]Send{s}, loadHistory(ctx)...)
	if len(hs) > historyCap {
		hs = hs[:historyCap]
	}
	if b, err := json.Marshal(hs); err == nil {
		_ = ctx.StorageSet(historyKey, string(b))
	}
}

// findGuard 按会话 id 取一条守护的下标,没有返回 -1。
func findGuard(gs []Guard, session string) int {
	for i := range gs {
		if gs[i].Session == session {
			return i
		}
	}
	return -1
}

// guardView 是给 CLI/Web 的守护视图:配置字段全给(面板要回填),运行态也全给
// (面板要回答「上次什么时候催的、催了几次、是不是已经自动停手了」)。
func guardView(g Guard, s Settings) map[string]any {
	eff := g.Effective(s)
	return map[string]any{
		"session": g.Session,
		"label":   g.Label,
		"enabled": g.Enabled,
		// 原始覆盖值(空/0 = 跟随全局),面板据此决定这一项要不要显示成「跟着全局」
		"prompt":   g.Prompt,
		"idleMin":  g.IdleMin,
		"everyMin": g.EveryMin,
		// 实际生效值,免得面板自己再算一遍全局与覆盖的合并
		"effPrompt":   eff.Prompt,
		"effIdleMin":  eff.IdleMin,
		"effEveryMin": eff.EveryMin,
		"sends":       g.Sends,
		"lastSent":    g.LastSent,
		"quietSince":  g.QuietSince,
		"streak":      g.Streak,
		"maxQuiet":    eff.MaxQuiet,
		"stoppedAt":   g.StoppedAt,
	}
}

func settingsView(s Settings) map[string]any {
	return map[string]any{
		"prompt": s.Prompt, "idleMin": s.IdleMin, "everyMin": s.EveryMin, "maxQuiet": s.MaxQuiet,
		"defaultPrompt": DefaultPrompt, "maxPromptLen": MaxPromptLen,
	}
}
