// Package reviewmesh is the builtin peer-review plugin case(设计见
// docs/design/plugin/03-stories.md 故事一与 docs/design/智能评审插件设计.md):
// 对工作区 diff 运行一个 reviewer Agent(codex 优先),解析其结构化
// findings 写回 Finding API,并发布通知(飞书 sink 会转发)。
//
// 会话形态(按用户约定):做 feature 的会话名不变;review 相关只有一个
// `<会话名>-review` 陪跑会话——reviewer 本身是宿主子进程(agent.run),
// 不再单独出现 review-mesh-jXXX 这类无含义会话。
package reviewmesh

import (
	"crypto/sha1"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

const (
	findingsBegin = "TTMUX_FINDINGS_BEGIN"
	findingsEnd   = "TTMUX_FINDINGS_END"
	// 自动互审轮次上限默认值,防 Agent 互相无限循环(评审设计 §10.1);
	// 可由设置页 rounds 配置或命令 --rounds 覆盖,见 resolveRounds。
	defaultAutoRounds = 3
	maxAutoRoundsCap  = 20 // 硬上限:配置再大也不放任无限互审
)

// resolveRounds 解析本次互审的轮次上限:命令 --rounds 优先,其次设置页
// rounds,再退回默认值;越界(<1 或 >cap)时夹到合法区间。
func resolveRounds(ctx *sdk.Ctx, args map[string]string) int {
	pick := func(s string) (int, bool) {
		if n, err := strconv.Atoi(strings.TrimSpace(s)); err == nil {
			return n, true
		}
		return 0, false
	}
	n := defaultAutoRounds
	if v, ok := pick(ctx.Config["rounds"]); ok {
		n = v
	}
	if args != nil {
		if v, ok := pick(args["rounds"]); ok {
			n = v
		}
	}
	if n < 1 {
		n = 1
	}
	if n > maxAutoRoundsCap {
		n = maxAutoRoundsCap
	}
	return n
}

// Activate registers the plugin's commands (sdk.Serve 的入口).
func Activate(ctx *sdk.Ctx) sdk.Plugin {
	return sdk.Plugin{
		Commands: map[string]sdk.CommandHandler{
			"review": review,
			"status": status,
			"watch":  watch,
		},
		Events: map[string]sdk.EventHandler{
			// 异步 reviewer 会话(手动 wait=false / 消亡兜底)的收尾
			"session:agent.exited": onAgentExited,
		},
	}
}

func onAgentExited(ctx *sdk.Ctx, payload json.RawMessage) error {
	var ev struct {
		Session string            `json:"session"`
		Job     string            `json:"job"`
		Labels  map[string]string `json:"labels"`
	}
	if err := json.Unmarshal(payload, &ev); err != nil {
		return err
	}
	switch {
	case ev.Labels["role"] == "reviewer":
		// 异步 reviewer 会话完成 → 收尾(解析 findings、落库、发通知)
		res, err := finalizeSession(ctx, ev.Job, ev.Session)
		if err != nil {
			return err
		}
		ctx.Logf("job %s finalized asynchronously: %d findings (%d blocking)", ev.Job, len(res.Findings), res.Blocking)
		return nil
	case ev.Labels["review:auto"] == "true":
		// 被跟踪的开发会话消亡:兜底一轮互审(陪跑在位时通常已审过,
		// 同一 diff 由存储哈希去重)。异步:收尾走上面的 reviewer 分支。
		workdir := ev.Labels["workdir"]
		if workdir == "" {
			ctx.Logf("auto-review skipped for %s: no workdir label", ev.Session)
			return nil
		}
		if ctx.SessionAlive(ev.Session + "-review") {
			// 陪跑监控还在:它的收尾检查会做最后一轮阻塞互审,这里再拉
			// 异步 reviewer 会话只会跟它抢同一份 diff(哈希竞态)+多出一个会话
			ctx.Logf("auto-review for %s deferred to its watch session", ev.Session)
			return nil
		}
		res, err := autoReviewOnce(ctx, ev.Session, workdir, resolveRounds(ctx, nil), false)
		if err != nil {
			ctx.Logf("auto-review for %s (%s): %v", ev.Session, workdir, err)
			return nil // 无 diff 等情况不算错误,不重试
		}
		if res.Reviewed {
			ctx.Logf("final auto-review launched for exited session %s", ev.Session)
		}
		return nil
	}
	return nil // 与本插件无关的会话,忽略
}

type reviewResult struct {
	Job      string        `json:"job"`
	Session  string        `json:"session,omitempty"` // 仅异步会话模式有
	Provider string        `json:"provider"`
	Findings []sdk.Finding `json:"findings,omitempty"`
	Blocking int           `json:"blocking"`
	Summary  string        `json:"summary,omitempty"`
	Waited   bool          `json:"waited"`
}

// review 命令:默认阻塞完成整轮审查(reviewer 是宿主子进程,不建会话);
// --wait false 时改为异步会话模式(收尾由会话退出事件驱动)。
func review(ctx *sdk.Ctx, args map[string]string) (any, error) {
	workdir := args["workdir"]
	provider := resolveProvider(ctx, args["provider"])
	if args["wait"] == "false" {
		return launchReviewSession(ctx, workdir, provider, "")
	}
	return runReview(ctx, workdir, provider)
}

// runReview 阻塞执行一轮审查:取 diff → agent.run 子进程 → 解析收尾。
func runReview(ctx *sdk.Ctx, workdir, provider string) (*reviewResult, error) {
	diff, jobID, err := prepDiff(ctx, workdir)
	if err != nil {
		return nil, err
	}
	fmt.Fprintf(os.Stderr, "[%s] reviewer(%s)审查中,job %s…\n", now(), provider, jobID)
	r, err := ctx.AgentRun(provider, reviewerPrompt(diff), workdir, 1800)
	if err != nil {
		return nil, err
	}
	fin, err := finalizeText(ctx, jobID, r.Output)
	if err != nil {
		return nil, fmt.Errorf("reviewer output not parseable: %w", err)
	}
	fin.Provider = r.Provider
	fin.Waited = true
	return fin, nil
}

// launchReviewSession 异步会话模式:reviewer 跑在一个 tmux 会话里,退出后
// 由 plugind 事件收尾。sessionName 为空时命名 review-<job>。
func launchReviewSession(ctx *sdk.Ctx, workdir, provider, sessionName string) (*reviewResult, error) {
	diff, jobID, err := prepDiff(ctx, workdir)
	if err != nil {
		return nil, err
	}
	if sessionName == "" {
		sessionName = "review-" + jobID
	}
	sess, err := ctx.AgentSpawn(sdk.SpawnReq{
		Provider:    provider,
		Prompt:      reviewerPrompt(diff),
		SessionName: sessionName,
		Workdir:     workdir,
		Job:         jobID,
		Labels:      map[string]string{"job": jobID, "role": "reviewer"},
	})
	if err != nil {
		return nil, err
	}
	ctx.Logf("job %s: reviewer %s spawned in session %s", jobID, provider, sess)
	return &reviewResult{Job: jobID, Session: sess, Provider: provider}, nil
}

// prepDiff 取可审查的 diff 并生成 job id;diff 为空视为无事可审。
func prepDiff(ctx *sdk.Ctx, workdir string) (sdk.DiffResult, string, error) {
	diff, err := ctx.WorkspaceDiff(workdir)
	if err != nil {
		return diff, "", err
	}
	if strings.TrimSpace(diff.Diff) == "" {
		return diff, "", fmt.Errorf("workspace has no reviewable diff")
	}
	return diff, fmt.Sprintf("j%d", time.Now().Unix()%1000000), nil
}

func resolveProvider(ctx *sdk.Ctx, arg string) string {
	if arg != "" {
		return arg
	}
	if p := ctx.Config["provider"]; p != "" {
		return p // 设置页配置的默认 reviewer
	}
	providers, err := ctx.AgentProviders()
	if err == nil {
		// codex 审 claude 的活,反向互审是默认策略(智能评审插件设计 §3)
		if providers["codex"] {
			return "codex"
		}
		if providers["claude"] {
			return "claude"
		}
	}
	return "claude"
}

// watch 在 `<会话名>-review` 会话里陪跑一个开发会话(建会话勾「自动互审」
// 时由 plugin track 拉起):画面静止 ≥30s 判定"一轮对话结束"→ 互审 →
// 意见 send 回原会话让 Agent 修改 → 修完再次空闲则复审;同一份 diff 只审
// 一次,最多 maxAutoRounds 轮。
func watch(ctx *sdk.Ctx, args map[string]string) (any, error) {
	dev, workdir := args["session"], args["workdir"]
	if dev == "" || workdir == "" {
		return nil, fmt.Errorf("usage: review-mesh.watch --session <dev> --workdir <abs-dir> [--rounds N]")
	}
	rounds := resolveRounds(ctx, args)
	ctx.Logf("watch: monitoring %s (workdir %s, max %d rounds)", dev, workdir, rounds)
	fmt.Fprintf(os.Stderr, "== review-mesh 陪跑 %s ==\n对话空闲 30s 即互审;意见自动回灌;同一 diff 只审一次,最多 %d 轮\n", dev, rounds)
	// 新一次陪跑 = 新一轮周期:清掉同名会话遗留的轮次/哈希,否则会话名
	// 复用时自动互审会被旧状态静默跳过
	_ = ctx.StorageSet("auto:"+dev, "")

	lastPane, stableSince := "", time.Time{}
	for {
		// 存活判定必须走 session.alive:capture 在会话消亡后会退回读日志
		// "成功"返回,曾让这个循环永远退不出去(陪跑会话变僵尸)
		if !ctx.SessionAlive(dev) {
			fmt.Fprintf(os.Stderr, "[%s] 开发会话已结束,做收尾检查\n", now())
			res, _ := autoReviewOnce(ctx, dev, workdir, rounds, true)
			return finish(ctx, dev, fmt.Sprintf("开发会话已结束，收尾检查 %d 个问题", res.Findings), "session exited")
		}
		out, err := ctx.SessionCapture(dev, 40)
		if err != nil { // 会话没了:收尾前做最后一轮兜底互审
			fmt.Fprintf(os.Stderr, "[%s] 开发会话已结束,做收尾检查\n", now())
			res, _ := autoReviewOnce(ctx, dev, workdir, rounds, true)
			return finish(ctx, dev, fmt.Sprintf("开发会话已结束，收尾检查 %d 个问题", res.Findings), "session exited")
		}
		sum := fmt.Sprintf("%x", sha1.Sum([]byte(out)))
		if sum != lastPane {
			lastPane, stableSince = sum, time.Now()
		} else if time.Since(stableSince) >= 30*time.Second {
			res, err := autoReviewOnce(ctx, dev, workdir, rounds, true)
			if err != nil {
				fmt.Fprintf(os.Stderr, "[%s] 互审失败: %v\n", now(), err)
			}
			// 干净就收工：作者已经空闲、这份 diff 也审过了没问题，再守下去只是一个
			// 每 5 秒抓屏的空转进程，人还得自己判断「它到底是审完了还是卡住了」。
			// 要再审就再开一轮——起一次的成本远低于一直挂着看不出状态。
			if res.Reviewed && res.Findings == 0 {
				return finish(ctx, dev, fmt.Sprintf("互审通过：这份改动没发现问题（第 %d 轮）", roundsDone(ctx, dev)), "clean")
			}
			if res.Exhausted {
				return finish(ctx, dev, fmt.Sprintf("已达 %d 轮上限，陪跑结束；要再审：roami plugin run review-mesh.review --workdir %s", rounds, workdir), "rounds-exhausted")
			}
			if res.Reviewed {
				lastPane = "" // 回灌后画面会变;重置指纹等下一轮
			}
		}
		time.Sleep(5 * time.Second)
	}
}

// finish 收工：把结论留在通知中心（会话马上就没了，日志跟着一起没），再把自己这条
// 陪跑会话关掉——树上不留一条已经不干活的死会话。
func finish(ctx *sdk.Ctx, dev, msg, reason string) (any, error) {
	fmt.Fprintf(os.Stderr, "[%s] %s\n", now(), msg)
	_ = ctx.NotificationPublish(sdk.Notification{
		Type: "review-mesh.done", Severity: "info",
		Title: "互审结束 · " + dev, Body: msg,
		DedupeKey: "review-mesh.done:" + dev,
	})
	self := dev + "-review"
	if ctx.SessionAlive(self) {
		// 自杀式关闭：这条命令就跑在那个会话里，kill 之后下面的 return 不一定还执行得到
		go func() { time.Sleep(2 * time.Second); _ = ctx.SessionKill(self) }()
	}
	return map[string]string{"stopped": reason}, nil
}

// roundsDone 读一下这轮陪跑已经审了几轮，只为把结论写清楚。
func roundsDone(ctx *sdk.Ctx, dev string) int {
	st := autoState{}
	if raw, err := ctx.StorageGet("auto:" + dev); err == nil && raw != "" {
		_ = json.Unmarshal([]byte(raw), &st)
	}
	return st.Rounds
}

type autoState struct {
	LastDiff string `json:"lastDiff"`
	Rounds   int    `json:"rounds"`
}

// autoReviewOnce 对 dev 会话的 workdir 做一轮受控互审:diff 为空/未变化/
// 轮次用尽(≥ maxRounds)都跳过;wait 时阻塞完成整轮并把 findings send 回
// dev 会话,不 wait 则拉起异步会话 `<dev>-review-final`(消亡兜底路径)。
//
// 返回 outcome 告诉调用方这一轮的下场:陪跑要不要收工全看它。
type outcome struct {
	Reviewed  bool // 真跑了一轮(没被 diff 未变/轮次用尽跳过)
	Findings  int  // 这一轮几个问题
	Exhausted bool // 轮次用尽,不会再有下一轮
}

func autoReviewOnce(ctx *sdk.Ctx, dev, workdir string, maxRounds int, wait bool) (outcome, error) {
	diff, err := ctx.WorkspaceDiff(workdir)
	if err != nil {
		return outcome{}, err
	}
	if strings.TrimSpace(diff.Diff) == "" {
		return outcome{}, nil
	}
	diffSum := fmt.Sprintf("%x", sha1.Sum([]byte(diff.Diff)))

	stateKey := "auto:" + dev
	st := autoState{}
	if raw, err := ctx.StorageGet(stateKey); err == nil && raw != "" {
		_ = json.Unmarshal([]byte(raw), &st)
	}
	if st.LastDiff == diffSum {
		return outcome{}, nil // 这份变更已审过(空闲但没新改动,或复审后未再动)
	}
	if st.Rounds >= maxRounds {
		fmt.Fprintf(os.Stderr, "[%s] 已达 %d 轮上限,不再自动复审(手动: roami plugin run review-mesh.review --workdir %s)\n",
			now(), maxRounds, workdir)
		return outcome{Exhausted: true}, nil
	}

	saveState := func() {
		raw, _ := json.Marshal(st)
		_ = ctx.StorageSet(stateKey, string(raw))
	}
	st.LastDiff, st.Rounds = diffSum, st.Rounds+1
	saveState()

	if !wait {
		_, err := launchReviewSession(ctx, workdir, resolveProvider(ctx, ""), dev+"-review-final")
		if err != nil {
			st.LastDiff = ""
			saveState()
			return outcome{}, err
		}
		return outcome{Reviewed: true}, nil
	}

	fmt.Fprintf(os.Stderr, "[%s] 第 %d 轮互审开始…\n", now(), st.Rounds)
	fin, err := runReview(ctx, workdir, resolveProvider(ctx, ""))
	if err != nil {
		st.LastDiff = "" // 撤销哈希登记,下次空闲可重试这份 diff(轮次仍计数)
		saveState()
		return outcome{Reviewed: true}, err
	}
	fmt.Fprintf(os.Stderr, "[%s] 第 %d 轮完成:%d 个 finding(blocking %d)\n",
		now(), st.Rounds, len(fin.Findings), fin.Blocking)

	if len(fin.Findings) > 0 && ctx.SessionAlive(dev) {
		msg := fixPrompt(fin.Job, fin.Findings)
		if err := ctx.SessionSend(dev, msg); err != nil {
			fmt.Fprintf(os.Stderr, "回灌失败: %v\n", err)
		} else {
			fmt.Fprintf(os.Stderr, "[%s] 意见已回灌 %s,等待修复后复审\n", now(), dev)
		}
	}
	return outcome{Reviewed: true, Findings: len(fin.Findings), Exhausted: st.Rounds >= maxRounds}, nil
}

// fixPrompt 是回灌给开发会话的单行修复指令(交互 TUI 里换行即提交)。
func fixPrompt(job string, findings []sdk.Finding) string {
	var b strings.Builder
	fmt.Fprintf(&b, "【review-mesh 互审 %s】发现 %d 个问题,请逐一修复: ", job, len(findings))
	for i, f := range findings {
		loc := f.File
		if f.Line > 0 {
			loc = fmt.Sprintf("%s:%d", f.File, f.Line)
		}
		fmt.Fprintf(&b, "%d) [%s] %s(%s)— %s ", i+1, f.Severity, f.Title, loc, oneline(f.Detail, 160))
	}
	b.WriteString("。修复完成后简要说明即可,我会自动复审。")
	return b.String()
}

func oneline(s string, max int) string {
	s = strings.Join(strings.Fields(s), " ")
	r := []rune(s)
	if len(r) > max {
		return string(r[:max]) + "…"
	}
	return s
}

func now() string { return time.Now().Format("15:04:05") }

// finalizeSession reads an async reviewer session's log and finalizes it.
func finalizeSession(ctx *sdk.Ctx, jobID, sess string) (*reviewResult, error) {
	logText, err := ctx.SessionLog(sess)
	if err != nil {
		return nil, err
	}
	res, err := finalizeText(ctx, jobID, logText)
	if err != nil {
		return nil, fmt.Errorf("reviewer output not parseable: %w (inspect: roami session capture %s)", err, sess)
	}
	res.Session = sess
	return res, nil
}

// finalizeText parses reviewer output, persists findings and publishes the
// summary notification. 阻塞(agent.run)与异步(会话日志)两条路径共用。
func finalizeText(ctx *sdk.Ctx, jobID, logText string) (*reviewResult, error) {
	findings, summary, err := ParseFindings(logText)
	if err != nil {
		return nil, err
	}
	res := &reviewResult{Job: jobID, Summary: summary}
	for i := range findings {
		findings[i].Job = jobID
		id, err := ctx.FindingCreate(findings[i])
		if err != nil {
			return nil, err
		}
		findings[i].ID = id
		if findings[i].Severity == "high" {
			res.Blocking++
		}
	}
	res.Findings = findings

	notifType := "review.completed"
	severity := "info"
	title := fmt.Sprintf("互审完成:%d 个 finding", len(findings))
	if res.Blocking > 0 {
		notifType = "finding.blocking"
		severity = "high"
		title = fmt.Sprintf("互审发现 %d 个 blocking finding(共 %d 个)", res.Blocking, len(findings))
	}
	body := summary
	for _, f := range findings {
		body += fmt.Sprintf("\n- [%s] %s", f.Severity, f.Title)
	}
	if err := ctx.NotificationPublish(sdk.Notification{
		Type: notifType, Severity: severity, Title: title,
		Body: strings.TrimSpace(body), DedupeKey: "review-mesh." + jobID,
	}); err != nil {
		ctx.Logf("notification publish failed: %v", err)
	}
	return res, nil
}

func status(ctx *sdk.Ctx, args map[string]string) (any, error) {
	findings, err := ctx.FindingList(args["job"], args["status"])
	if err != nil {
		return nil, err
	}
	open, blocking := 0, 0
	for _, f := range findings {
		if f.Status == "open" {
			open++
			if f.Severity == "high" {
				blocking++
			}
		}
	}
	return map[string]any{
		"total": len(findings), "open": open, "blocking": blocking,
		"findings": findings,
	}, nil
}

func reviewerPrompt(diff sdk.DiffResult) string {
	var b strings.Builder
	b.WriteString("你是一名严格的资深代码评审员,对下面的变更做 peer review。\n")
	b.WriteString("要求:\n")
	b.WriteString("- 只报告真实、可定位的问题(bug、安全、数据丢失、明显性能问题),不要风格意见。\n")
	b.WriteString("- 每个问题给出文件路径与行号(基于 diff 的新文件行号)。\n")
	b.WriteString("- severity 取 high(必须阻塞合并)/ medium / low。\n")
	b.WriteString("- 没有问题就输出空数组,不要编造。\n\n")
	b.WriteString("输出格式(严格遵守,便于机器解析):\n")
	b.WriteString("1) 先输出一行总结:REVIEW_SUMMARY: <一句话结论>\n")
	b.WriteString(fmt.Sprintf("2) 然后在 %s 与 %s 两个标记行之间输出 JSON 数组,元素形如:\n", findingsBegin, findingsEnd))
	b.WriteString(`   {"severity":"high","title":"...","file":"path/to/file.go","line":42,"detail":"..."}` + "\n\n")
	b.WriteString(fmt.Sprintf("当前分支: %s\n变更统计:\n%s\n", diff.Branch, diff.Stat))
	b.WriteString("完整 diff:\n```diff\n" + diff.Diff + "\n```\n")
	return b.String()
}

var summaryRe = regexp.MustCompile(`REVIEW_SUMMARY:\s*(.+)`)

// ParseFindings extracts the fenced findings JSON and summary line from the
// reviewer output. Exported for unit tests.
func ParseFindings(logText string) ([]sdk.Finding, string, error) {
	summary := ""
	// 取最后一次匹配:会话日志里 prompt 回显也含 REVIEW_SUMMARY 占位行
	if ms := summaryRe.FindAllStringSubmatch(logText, -1); len(ms) > 0 {
		summary = strings.TrimSpace(ms[len(ms)-1][1])
	}
	if strings.HasPrefix(summary, "<") { // reviewer 未输出总结时残留占位符
		summary = ""
	}
	begin := strings.LastIndex(logText, findingsBegin)
	end := strings.LastIndex(logText, findingsEnd)
	if begin < 0 || end < 0 || end <= begin {
		return nil, summary, fmt.Errorf("markers %s/%s not found", findingsBegin, findingsEnd)
	}
	raw := logText[begin+len(findingsBegin) : end]
	// 剥掉可能的代码栅栏与终端噪音,定位第一个 [ 到最后一个 ]
	i, j := strings.Index(raw, "["), strings.LastIndex(raw, "]")
	if i < 0 || j <= i {
		return []sdk.Finding{}, summary, nil // 空数组:reviewer 没发现问题
	}
	var findings []sdk.Finding
	if err := json.Unmarshal([]byte(raw[i:j+1]), &findings); err != nil {
		return nil, summary, fmt.Errorf("findings JSON invalid: %w", err)
	}
	for k := range findings {
		if findings[k].Severity == "" {
			findings[k].Severity = "medium"
		}
	}
	return findings, summary, nil
}
