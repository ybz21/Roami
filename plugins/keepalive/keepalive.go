// Package keepalive is the builtin session-guard plugin: 它替人「看着」那些
// 会话——Agent 干着干着停下来等一句话是常态,它没死,只是在等,而你可能几个
// 小时后才发现。本插件按会话记一张守护表,发现某个会话安静得太久就替你说一句,
// 把它推回去接着干。
//
// 说什么由一张有序规则表决定(rules.go):屏幕上出现「断线」那类字样就说
// 「从断掉的地方接着说」,其余情况用兜底语。默认兜底语不是「继续」,理由见
// DefaultPrompt。
//
// 判「还动不动」看的是**屏幕指纹**,不是 tmux 的 session_activity:后者在我们
// 自己往会话里 paste 那句话的时候同样会跳,拿它判断等于自己跟自己确认「它动了」。
//
// 常驻形态同 roam.cron / im.listen:宿主的 watcher 调度器(manifest watchers /
// onSchedule)尚未落地,循环跑在专用 tmux 会话 `_ttmux-keepalive` 里,由 plugind
// 按「插件有没有活要干」自动拉起、掉了重拉(见 internal/plugin/daemon.go)。
package keepalive

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"ttmux-cli-go/pkg/plugin/sdk"
)

// Activate registers the plugin's commands (sdk.Serve 的入口)。
func Activate(ctx *sdk.Ctx) sdk.Plugin {
	return sdk.Plugin{
		Commands: map[string]sdk.CommandHandler{
			"list":     list,
			"on":       on,
			"off":      off,
			"all":      all,
			"settings": settingsCmd,
			"rules":    rulesCmd,
			"dryrun":   dryrun,
			"ping":     ping,
			"history":  historyCmd,
			"tick":     tickCmd,
			"serve":    serve,
		},
	}
}

// list 一次给齐面板要的全部东西:所有会话(各自带着守护状态)、全局默认、规则表、
// 巡检还在不在跑。分成几条命令就会出现「会话列表是新的、守护状态是旧的」。
func list(ctx *sdk.Ctx, args map[string]string) (any, error) {
	st, err := loadSettings(ctx)
	if err != nil {
		return nil, err
	}
	guards, err := loadGuards(ctx)
	if err != nil {
		return nil, err
	}
	sessions, err := ctx.SessionListAll()
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	rows := make([]map[string]any, 0, len(sessions))
	for _, s := range sessions {
		seen[s.Session] = true
		row := map[string]any{
			"session": s.Session, "label": s.Label, "agent": s.Agent, "dir": s.Dir,
			"attached": s.Attached, "idleSec": s.IdleSec, "created": s.Created,
		}
		if i := findGuard(guards, s.Session); i >= 0 {
			row["guard"] = guardView(guards[i], st)
		}
		rows = append(rows, row)
	}
	// 会话已经没了、守护表里还留着的那些。正常由巡检顺手清掉;巡检没在跑时
	// 它们会一直挂着,面板要能说出「这条守的是个已经结束的会话」而不是假装
	// 没这回事。
	orphans := make([]map[string]any, 0)
	for _, g := range guards {
		if !seen[g.Session] {
			orphans = append(orphans, guardView(g, st))
		}
	}
	rules := make([]map[string]any, 0)
	for _, r := range loadRules(ctx) {
		rules = append(rules, ruleView(r))
	}
	tickAt := readInt(ctx, tickKey)
	now := time.Now().Unix()
	out := map[string]any{
		"settings": settingsView(st),
		"rules":    rules,
		"sessions": rows,
		"orphans":  orphans,
		"guarded":  CountEnabled(guards),
		"tickAt":   tickAt,
		"tickSec":  int(tickInterval / time.Second),
		// 「它在不在跑」——这一页最要紧的一句话。配得再漂亮,没人巡检就一条都不会发。
		"running": tickAt > 0 && now-tickAt <= staleAfterSec,
	}
	if tickAt > 0 {
		out["tickAgoSec"] = now - tickAt
	}
	return out, nil
}

// on 开始守护一个会话(已有则更新它的逐会话覆盖)。
func on(ctx *sdk.Ctx, args map[string]string) (any, error) {
	session := strings.TrimSpace(args["session"])
	if session == "" {
		return nil, fmt.Errorf("usage: keepalive.on --session <会话 id> [--prompt <守护语>] [--idleMin N] [--everyMin N]")
	}
	st, err := loadSettings(ctx)
	if err != nil {
		return nil, err
	}
	guards, err := loadGuards(ctx)
	if err != nil {
		return nil, err
	}
	live, err := ctx.SessionListAll()
	if err != nil {
		return nil, err
	}
	label, found := "", false
	for _, s := range live {
		if s.Session == session {
			label, found = s.Label, true
			break
		}
	}
	if !found {
		return nil, fmt.Errorf("没有叫 %q 的会话(守护按会话 id 记,不认展示名)", session)
	}

	i := findGuard(guards, session)
	if i < 0 {
		guards = append(guards, Guard{Session: session})
		i = len(guards) - 1
	}
	g := &guards[i]
	g.Label, g.Enabled = label, true
	// 重新开启时把上一轮的连败计数与「已停手」标记清掉:用户点开关那一下
	// 表达的就是「再试试」,不该一开就因为旧账立刻又停手。
	g.Streak, g.StoppedAt, g.Responded = 0, 0, false
	// 安静起点重新计:刚开守护不该因为会话已经安静了半天就立刻催一句——
	// 你要的是「从现在起看着它」。
	g.QuietSince, g.Hash = time.Now().Unix(), ""
	if v, ok := args["prompt"]; ok {
		g.Prompt = TrimPrompt(v)
	}
	if v, ok := args["idleMin"]; ok {
		g.IdleMin = atoiOr(v, 0)
	}
	if v, ok := args["everyMin"]; ok {
		g.EveryMin = atoiOr(v, 0)
	}
	if err := saveGuards(ctx, guards); err != nil {
		return nil, err
	}
	eff := g.Effective(st)
	ctx.Logf("开始守护 %s(%s):安静 %d 分钟就催一句,最快 %d 分钟一次", label, session, eff.IdleMin, eff.EveryMin)
	return guardView(*g, st), nil
}

// off 停止守护一个会话。配置留着(下次打开还是老样子),只是不再巡检它。
func off(ctx *sdk.Ctx, args map[string]string) (any, error) {
	session := strings.TrimSpace(args["session"])
	if session == "" {
		return nil, fmt.Errorf("usage: keepalive.off --session <会话 id>")
	}
	guards, err := loadGuards(ctx)
	if err != nil {
		return nil, err
	}
	i := findGuard(guards, session)
	if i < 0 {
		return nil, fmt.Errorf("会话 %q 本来就没在守护", session)
	}
	guards[i].Enabled, guards[i].StoppedAt = false, 0
	if err := saveGuards(ctx, guards); err != nil {
		return nil, err
	}
	ctx.Logf("停止守护 %s", session)
	st, _ := loadSettings(ctx)
	return guardView(guards[i], st), nil
}

// all 一键守护/取消全部会话。--agentOnly true(默认)时只挑认得出是 Agent 的
// 那些:往一个裸 shell 里打一句话,换来的是一行 command not found。
//
// 注意这是**一次性**动作,不是一个开关:之后新建的会话不会自动进来。
// 每一条守护都必须有人亲手打开过——每一条都会替用户花钱、往他的会话里写东西。
func all(ctx *sdk.Ctx, args map[string]string) (any, error) {
	want := truthy(args["on"])
	agentOnly := args["agentOnly"] == "" || truthy(args["agentOnly"])
	guards, err := loadGuards(ctx)
	if err != nil {
		return nil, err
	}
	sessions, err := ctx.SessionListAll()
	if err != nil {
		return nil, err
	}
	now := time.Now().Unix()
	changed, skipped := []string{}, []string{}
	if !want {
		for i := range guards {
			if guards[i].Enabled {
				guards[i].Enabled, guards[i].StoppedAt = false, 0
				changed = append(changed, guards[i].Session)
			}
		}
	} else {
		for _, s := range sessions {
			if agentOnly && s.Agent == "" {
				skipped = append(skipped, s.Session)
				continue
			}
			i := findGuard(guards, s.Session)
			if i < 0 {
				guards = append(guards, Guard{Session: s.Session})
				i = len(guards) - 1
			}
			guards[i].Label = s.Label
			if guards[i].Enabled {
				continue
			}
			guards[i].Enabled = true
			guards[i].Streak, guards[i].StoppedAt, guards[i].Responded = 0, 0, false
			guards[i].QuietSince, guards[i].Hash = now, ""
			changed = append(changed, s.Session)
		}
	}
	if err := saveGuards(ctx, guards); err != nil {
		return nil, err
	}
	ctx.Logf("一键%s:动了 %d 个会话,跳过 %d 个", map[bool]string{true: "守护", false: "取消"}[want], len(changed), len(skipped))
	return map[string]any{"on": want, "changed": changed, "skipped": skipped, "guarded": CountEnabled(guards)}, nil
}

// settingsCmd 不带参数就是读,带参数就是改(只改传进来的那几项)。
func settingsCmd(ctx *sdk.Ctx, args map[string]string) (any, error) {
	st, err := loadSettings(ctx)
	if err != nil {
		return nil, err
	}
	touched := false
	if v, ok := args["prompt"]; ok {
		if p := TrimPrompt(v); p != "" {
			st.Prompt, touched = p, true
		}
	}
	if v, ok := args["idleMin"]; ok {
		st.IdleMin, touched = atoiOr(v, st.IdleMin), true
	}
	if v, ok := args["everyMin"]; ok {
		st.EveryMin, touched = atoiOr(v, st.EveryMin), true
	}
	if v, ok := args["maxQuiet"]; ok {
		// maxQuiet 允许 0(= 永不自动停手),不能套 atoiOr 的「0 视作没填」
		if n, e := strconv.Atoi(strings.TrimSpace(v)); e == nil && n >= 0 {
			st.MaxQuiet, touched = n, true
		}
	}
	if touched {
		if err := saveSettings(ctx, st); err != nil {
			return nil, err
		}
		st, _ = loadSettings(ctx)
		ctx.Logf("全局默认已更新:安静 %d 分钟催一句,最快 %d 分钟一次,连催 %d 次没反应就停手",
			st.IdleMin, st.EveryMin, st.MaxQuiet)
	}
	return settingsView(st), nil
}

// rulesCmd 读或整表覆写守护语规则。--rules 收一段 JSON 数组(面板那边整表提交:
// 规则的语义在**顺序**里,逐条增删改的接口反而更容易把顺序搞乱)。
func rulesCmd(ctx *sdk.Ctx, args map[string]string) (any, error) {
	if raw, ok := args["rules"]; ok && strings.TrimSpace(raw) != "" {
		var rs []Rule
		if err := json.Unmarshal([]byte(raw), &rs); err != nil {
			return nil, fmt.Errorf("--rules 得是一段 JSON 数组: %w", err)
		}
		if err := saveRules(ctx, rs); err != nil {
			return nil, err
		}
		ctx.Logf("守护语规则已更新,共 %d 条", len(NormalizeRules(rs)))
	}
	out := make([]map[string]any, 0)
	for _, r := range loadRules(ctx) {
		out = append(out, ruleView(r))
	}
	return map[string]any{"rules": out, "count": len(out)}, nil
}

// dryrun 拿一个会话此刻的屏幕试一遍规则表,只回答「会命中哪条、会发什么」——
// 不发送、不落库、不动任何状态。面板「守护语规则」抽屉里那个「试一下」就是它:
// 没有它,用户填完一条匹配串只能等下一次真出事才知道对不对,而那正是最不想试错
// 的时刻。--rules 可选,面板把**还没保存的草稿**传进来试。
func dryrun(ctx *sdk.Ctx, args map[string]string) (any, error) {
	session := strings.TrimSpace(args["session"])
	if session == "" {
		return nil, fmt.Errorf("usage: keepalive.dryrun --session <会话 id> [--rules <JSON>]")
	}
	st, err := loadSettings(ctx)
	if err != nil {
		return nil, err
	}
	rules := loadRules(ctx)
	if raw := strings.TrimSpace(args["rules"]); raw != "" {
		var draft []Rule
		if err := json.Unmarshal([]byte(raw), &draft); err != nil {
			return nil, fmt.Errorf("--rules 得是一段 JSON 数组: %w", err)
		}
		rules = NormalizeRules(draft)
	}
	guards, err := loadGuards(ctx)
	if err != nil {
		return nil, err
	}
	fallback, nth := st.Prompt, 1
	if i := findGuard(guards, session); i >= 0 {
		fallback, nth = guards[i].Effective(st).Prompt, guards[i].Sends+1
	}
	screen, cerr := ctx.SessionCapture(session, CaptureLines)
	if cerr != nil {
		return nil, fmt.Errorf("读不到会话 %s 的屏幕: %w", session, cerr)
	}
	prompt, rule := PickPrompt(rules, screen, nth, fallback)
	return map[string]any{"session": session, "prompt": prompt, "rule": rule, "nth": nth}, nil
}

// ping 立刻对一个会话催一次,不管它此刻安不安静——面板上的「催一下」就是它,
// 用来验证「这条守护配出来到底会发什么」。
func ping(ctx *sdk.Ctx, args map[string]string) (any, error) {
	session := strings.TrimSpace(args["session"])
	if session == "" {
		return nil, fmt.Errorf("usage: keepalive.ping --session <会话 id> [--prompt <这一次要发的话>]")
	}
	st, err := loadSettings(ctx)
	if err != nil {
		return nil, err
	}
	guards, err := loadGuards(ctx)
	if err != nil {
		return nil, err
	}
	label, i := session, findGuard(guards, session)
	fallback := st.Prompt
	nth := 1
	if i >= 0 {
		label, fallback, nth = guards[i].Label, guards[i].Effective(st).Prompt, guards[i].Sends+1
	}
	text, rule := TrimPrompt(args["prompt"]), -1
	if text == "" {
		// 手动催也走规则表:面板上点「催一下」问的正是「这条守护现在会发什么」,
		// 给一句和自动催不一样的话,这个按钮就白给了。
		screen, _ := ctx.SessionCapture(session, CaptureLines)
		text, rule = PickPrompt(loadRules(ctx), screen, nth, fallback)
	}
	now := time.Now().Unix()
	sendErr := ctx.SessionSend(session, text)
	rec := Send{At: now, Session: session, Label: label, Prompt: text, Trigger: "manual", Rule: rule, Nth: nth}
	if sendErr != nil {
		rec.Error = sendErr.Error()
	}
	record(ctx, rec)
	if sendErr != nil {
		return nil, sendErr
	}
	if i >= 0 {
		// 手动催也是催:最小间隔要认它,免得点完按钮下一分钟循环又补一句。
		// 但不计连败——那是给「自动催了没反应」用的账,手动的不该往里记。
		guards[i].Sends++
		guards[i].LastSent, guards[i].QuietSince = now, now
		guards[i].Responded = false
		if err := saveGuards(ctx, guards); err != nil {
			return nil, err
		}
	}
	ctx.Logf("已对 %s 发出「%s」", session, text)
	return map[string]any{"session": session, "prompt": text, "rule": rule, "at": now}, nil
}

// historyCmd 发送记录,新的在前。
func historyCmd(ctx *sdk.Ctx, args map[string]string) (any, error) {
	hs := loadHistory(ctx)
	limit := atoiOr(args["limit"], 50)
	if limit > len(hs) {
		limit = len(hs)
	}
	return map[string]any{"count": len(hs), "sends": hs[:limit]}, nil
}

// ── 小工具 ──

func atoiOr(s string, def int) int {
	if n, err := strconv.Atoi(strings.TrimSpace(s)); err == nil && n > 0 {
		return n
	}
	return def
}

func truthy(s string) bool {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

func readInt(ctx *sdk.Ctx, key string) int64 {
	raw, err := ctx.StorageGet(key)
	if err != nil {
		return 0
	}
	n, _ := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
	return n
}
