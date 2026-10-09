// Package cron is the builtin scheduled-task plugin. 它在插件私有 storage 里
// 维护一张定时任务表,由常驻会话 cron.serve 按点巡检触发(或系统 crontab 周期
// 调 cron.tick 无常驻触发)。排期用标准 5 段 cron 表达式(见 schedule.go)。
// 每个任务到点执行两类动作之一:定时启动已注册 Agent 干活(可选保持交互会话)、
// 或跑一条 shell 命令。
//
// 为什么不用 manifest 的 watchers/onSchedule:那套宿主调度器(docs/design/
// plugin/08-roadmap.md 阶段 2)尚未落地。本插件复用既有的「常驻会话跑循环」
// 形态(同 review-mesh.watch、im.listen),宿主代码零改动。
package cron

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"ttmux-cli-go/pkg/plugin/sdk"
)

// storeKey 是任务表在插件 KV 里的键(整表一个 JSON 数组,同 review-mesh 存法)。
const storeKey = "jobs"

// tickInterval 是 cron.serve 常驻循环的巡检周期。到期判定精度即此粒度。
const tickInterval = 15 * time.Second

// Job 是一条定时任务。排期由 Cron(5 段 cron 表达式)描述(见 schedule.go)。
type Job struct {
	Name    string `json:"name"`
	Cron    string `json:"cron"`   // 标准 5 段 cron 表达式(见 schedule.go)
	Action  string `json:"action"` // agent | exec
	Enabled bool   `json:"enabled"`

	// action=agent(定时启动已注册 Agent 干活)
	Provider    string `json:"provider,omitempty"`
	Prompt      string `json:"prompt,omitempty"`
	Workdir     string `json:"workdir,omitempty"`
	Interactive bool   `json:"interactive,omitempty"` // true=保持交互 TUI 会话(可 attach 续聊);默认跑完退出
	// action=exec(定时跑 shell 命令,经 sh -lc)
	Command string `json:"command,omitempty"`

	// 跑完通知我：拉 Agent 的等会话退出、跑命令的等命令返回，通知进 Roam 通知流
	// (装了 IM 并绑定通知的话，同一条会渲染成飞书卡片)。
	Notify bool `json:"notify,omitempty"`
	// 产物文件(可选,支持 ~)：通知里带上它的路径、大小与末段——
	// 「跑完了」这句话本身没用,人要的是结果在哪
	Artifact string `json:"artifact,omitempty"`

	NextRun int64 `json:"nextRun,omitempty"` // 下次触发(unix 秒)
	LastRun int64 `json:"lastRun,omitempty"` // 上次触发(unix 秒)
	Runs    int   `json:"runs,omitempty"`    // 累计触发次数
}

// Activate registers the plugin's commands (sdk.Serve 的入口)。
func Activate(ctx *sdk.Ctx) sdk.Plugin {
	return sdk.Plugin{
		Events: map[string]sdk.EventHandler{
			// 拉 Agent 的任务:会话退出才算这活干完(触发成功 ≠ 活干完了)
			"session:agent.exited": onAgentExited,
		},
		Commands: map[string]sdk.CommandHandler{
			"add":     add,
			"list":    list,
			"remove":  remove,
			"enable":  enable,
			"disable": disable,
			"run":     runNow,
			"runs":    runsCmd,
			"preview": preview,
			"tick":    tick,
			"serve":   serve,
		},
	}
}

// ── 任务表存取(整表一个 JSON,读改写)──

func loadJobs(ctx *sdk.Ctx) ([]Job, error) {
	raw, err := ctx.StorageGet(storeKey)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(raw) == "" {
		return nil, nil
	}
	var jobs []Job
	if err := json.Unmarshal([]byte(raw), &jobs); err != nil {
		return nil, fmt.Errorf("任务表损坏,无法解析: %w", err)
	}
	return jobs, nil
}

func saveJobs(ctx *sdk.Ctx, jobs []Job) error {
	b, err := json.Marshal(jobs)
	if err != nil {
		return err
	}
	return ctx.StorageSet(storeKey, string(b))
}

// ── 命令 handler ──

// add 添加或(按 name)更新一条定时任务。
func add(ctx *sdk.Ctx, args map[string]string) (any, error) {
	name := strings.TrimSpace(args["name"])
	if name == "" {
		return nil, fmt.Errorf("usage: cron.add --name <名> --cron '<分 时 日 月 周>' [--action agent|exec] ...")
	}
	cronExpr := strings.TrimSpace(args["cron"])
	if err := validateCron(cronExpr); err != nil {
		return nil, err
	}
	action := args["action"]
	if action == "" {
		action = "agent"
	}
	job := Job{
		Name:     name,
		Cron:     cronExpr,
		Action:   action,
		Enabled:  true,
		Provider: args["provider"],
		Prompt:   args["prompt"],
		Workdir:  args["workdir"],
		Command:  args["command"],
		Artifact: strings.TrimSpace(args["artifact"]),
	}
	// --interactive true/1 → 拉 Agent 时保持交互会话(仅 action=agent 有意义)
	if v := strings.TrimSpace(args["interactive"]); v == "true" || v == "1" {
		job.Interactive = true
	}
	// --notify true/1 → 跑完发通知(拉 Agent 等会话退出,跑命令等命令返回)
	if v := strings.TrimSpace(args["notify"]); v == "true" || v == "1" {
		job.Notify = true
	}
	if err := validateAction(job); err != nil {
		return nil, err
	}
	next, err := nextRun(job, time.Now())
	if err != nil {
		return nil, err
	}
	job.NextRun = next.Unix()

	jobs, err := loadJobs(ctx)
	if err != nil {
		return nil, err
	}
	replaced := false
	for i := range jobs {
		if jobs[i].Name == name {
			// 更新时保留累计计数与启停状态(启停由 enable/disable 专管,
			// 编辑配置不该顺手把禁用的任务重新点亮),其余字段整体替换。
			job.Runs, job.LastRun, job.Enabled = jobs[i].Runs, jobs[i].LastRun, jobs[i].Enabled
			jobs[i] = job
			replaced = true
			break
		}
	}
	if !replaced {
		jobs = append(jobs, job)
	}
	if err := saveJobs(ctx, jobs); err != nil {
		return nil, err
	}
	verb := "已添加"
	if replaced {
		verb = "已更新"
	}
	ctx.Logf("%s定时任务 %s(cron: %s),下次触发 %s", verb, name, job.Cron, time.Unix(job.NextRun, 0).Format("2006-01-02 15:04:05"))
	return jobView(job), nil
}

// preview 不落库,给定一条 cron 表达式算出接下来几次触发时刻——供设置页的
// 编辑器实时预览「这么配下次啥时候跑」。--cron <表达式> [--count N(默认5)]。
func preview(ctx *sdk.Ctx, args map[string]string) (any, error) {
	s, err := parseCron(strings.TrimSpace(args["cron"]))
	if err != nil {
		return nil, err
	}
	count := 5
	if n, e := strconv.Atoi(strings.TrimSpace(args["count"])); e == nil && n > 0 && n <= 20 {
		count = n
	}
	times := make([]string, 0, count)
	t := time.Now()
	for i := 0; i < count; i++ {
		next, nerr := s.next(t)
		if nerr != nil {
			return nil, nerr
		}
		times = append(times, next.Format("2006-01-02 15:04:05"))
		t = next
	}
	return map[string]any{"cron": strings.TrimSpace(args["cron"]), "next": times}, nil
}

// list 列出全部任务及下次触发时间(按下次触发时间升序)。
func list(ctx *sdk.Ctx, args map[string]string) (any, error) {
	jobs, err := loadJobs(ctx)
	if err != nil {
		return nil, err
	}
	sort.Slice(jobs, func(i, j int) bool { return jobs[i].NextRun < jobs[j].NextRun })
	views := make([]map[string]any, 0, len(jobs))
	for _, j := range jobs {
		views = append(views, jobView(j))
	}
	return map[string]any{"count": len(views), "jobs": views}, nil
}

// remove 按 name 删除一条任务。
func remove(ctx *sdk.Ctx, args map[string]string) (any, error) {
	name := strings.TrimSpace(args["name"])
	if name == "" {
		return nil, fmt.Errorf("usage: cron.remove --name <名>")
	}
	jobs, err := loadJobs(ctx)
	if err != nil {
		return nil, err
	}
	kept := jobs[:0]
	removed := false
	for _, j := range jobs {
		if j.Name == name {
			removed = true
			continue
		}
		kept = append(kept, j)
	}
	if !removed {
		return nil, fmt.Errorf("没有名为 %q 的定时任务", name)
	}
	dropRuns(ctx, name)
	if err := saveJobs(ctx, kept); err != nil {
		return nil, err
	}
	ctx.Logf("已删除定时任务 %s", name)
	return map[string]any{"removed": name}, nil
}

// enable 启用一条任务;若排期落后(禁用期间攒下的过期点),就地快进到未来的
// 下一个触发点,避免一启用就立刻补跑。
func enable(ctx *sdk.Ctx, args map[string]string) (any, error) { return setEnabled(ctx, args, true) }

// disable 停用一条任务:保留配置与排期,只是巡检时不再触发。
func disable(ctx *sdk.Ctx, args map[string]string) (any, error) { return setEnabled(ctx, args, false) }

func setEnabled(ctx *sdk.Ctx, args map[string]string, on bool) (any, error) {
	name := strings.TrimSpace(args["name"])
	if name == "" {
		return nil, fmt.Errorf("usage: cron.%s --name <名>", map[bool]string{true: "enable", false: "disable"}[on])
	}
	jobs, err := loadJobs(ctx)
	if err != nil {
		return nil, err
	}
	for i := range jobs {
		if jobs[i].Name != name {
			continue
		}
		jobs[i].Enabled = on
		if on {
			// 重新算排期:禁用期间 NextRun 可能已成过去时,直接快进到未来。
			next, nerr := nextRun(jobs[i], time.Now())
			if nerr != nil {
				return nil, nerr
			}
			jobs[i].NextRun = next.Unix()
		}
		if err := saveJobs(ctx, jobs); err != nil {
			return nil, err
		}
		verb := "已启用"
		if !on {
			verb = "已停用"
		}
		ctx.Logf("%s定时任务 %s", verb, name)
		return jobView(jobs[i]), nil
	}
	return nil, fmt.Errorf("没有名为 %q 的定时任务", name)
}

// runNow 立即触发一条任务一次,不改动它的排期(NextRun 不变),便于验证配置。
func runNow(ctx *sdk.Ctx, args map[string]string) (any, error) {
	name := strings.TrimSpace(args["name"])
	if name == "" {
		return nil, fmt.Errorf("usage: cron.run --name <名>")
	}
	jobs, err := loadJobs(ctx)
	if err != nil {
		return nil, err
	}
	for i := range jobs {
		if jobs[i].Name != name {
			continue
		}
		res, ferr := fireJob(ctx, &jobs[i], "manual")
		if ferr != nil {
			return nil, ferr
		}
		if err := saveJobs(ctx, jobs); err != nil {
			return nil, err
		}
		return map[string]any{"fired": name, "result": res}, nil
	}
	return nil, fmt.Errorf("没有名为 %q 的定时任务", name)
}

// tick 巡检一次:触发所有已启用且到期的任务,并把它们排到下一次。
// 无常驻场景可让系统 crontab 周期性调它(如每分钟一次)。幂等:未到期不动。
func tick(ctx *sdk.Ctx, args map[string]string) (any, error) {
	fired, err := tickOnce(ctx)
	if err != nil {
		return nil, err
	}
	return map[string]any{"fired": fired, "count": len(fired)}, nil
}

// serve 常驻调度器:每 tickInterval 巡检一次,直到进程被回收(plugin run 的
// invoke 上限 24h)。跑在专用 tmux 会话里可 attach 看日志:
//
//	tmux new-session -d -s _ttmux-cron 'ttmux plugin run cron.serve'
func serve(ctx *sdk.Ctx, args map[string]string) (any, error) {
	fmt.Fprintf(os.Stderr, "[%s] cron 调度器启动,每 %s 巡检一次\n", now(), tickInterval)
	ctx.Logf("scheduler loop started (tick=%s)", tickInterval)
	for {
		fired, err := tickOnce(ctx)
		if err != nil {
			fmt.Fprintf(os.Stderr, "[%s] 巡检出错: %v\n", now(), err)
		} else if len(fired) > 0 {
			fmt.Fprintf(os.Stderr, "[%s] 触发 %d 个任务: %s\n", now(), len(fired), strings.Join(fired, ", "))
		}
		time.Sleep(tickInterval)
	}
}

// ── 调度核心 ──

// tickOnce 触发所有到期任务并推进排期,返回本轮触发的任务名。
func tickOnce(ctx *sdk.Ctx) ([]string, error) {
	jobs, err := loadJobs(ctx)
	if err != nil {
		return nil, err
	}
	now := time.Now()
	fired := []string{}
	changed := false
	for i := range jobs {
		j := &jobs[i]
		if !j.Enabled || j.NextRun == 0 || time.Unix(j.NextRun, 0).After(now) {
			continue
		}
		if _, ferr := fireJob(ctx, j, "schedule"); ferr != nil {
			// 单个任务触发失败不阻断其余;记日志,排期照常推进避免热循环重试
			fmt.Fprintf(os.Stderr, "[%s] 任务 %s 触发失败: %v\n", nowStr(now), j.Name, ferr)
		} else {
			fired = append(fired, j.Name)
		}
		next, nerr := nextRun(*j, now)
		if nerr != nil {
			fmt.Fprintf(os.Stderr, "[%s] 任务 %s 排期推进失败,禁用: %v\n", nowStr(now), j.Name, nerr)
			j.Enabled = false
		} else {
			j.NextRun = next.Unix()
		}
		changed = true
	}
	if changed {
		if err := saveJobs(ctx, jobs); err != nil {
			return fired, err
		}
	}
	return fired, nil
}

// fireJob 执行一条任务的动作,并就地更新其 LastRun/Runs 计数,再落一条执行记录。
//
// trigger 是「谁按的」:schedule=到点触发,manual=面板上的「立即触发」。
// 记录哪怕写不进去也不影响这次触发的结果——它只是给人看的(见 recordRun)。
func fireJob(ctx *sdk.Ctx, j *Job, trigger string) (any, error) {
	j.Runs++
	j.LastRun = time.Now().Unix()
	rec := Run{Name: j.Name, At: j.LastRun, Trigger: trigger, Action: j.Action}

	var res any
	var err error
	switch j.Action {
	case "agent":
		res, err = fireAgent(ctx, j)
	case "exec":
		res, err = fireExec(ctx, j)
	default:
		err = fmt.Errorf("未知动作 %q", j.Action)
	}

	rec.OK = err == nil
	if err != nil {
		rec.Error = err.Error()
	}
	if m, okMap := res.(map[string]any); okMap {
		if s, okS := m["session"].(string); okS {
			rec.Session = s
		}
		rec.Interactive = j.Interactive
		if e, okE := m["exit"].(int); okE {
			rec.Exit = &e
		}
		if o, okO := m["output"].(string); okO {
			rec.Output = tailStr(o, 4000)
		}
	}
	// 命令跑完了但 exit≠0 —— 对人来说这就是「这次没成」，不该在记录里画一颗绿点。
	// （动作本身有没有发起成功是另一回事，那种失败上面已经填了 Error。）
	if rec.Exit != nil && *rec.Exit != 0 {
		rec.OK = false
	}
	recordRun(ctx, rec)
	return res, err
}

func fireAgent(ctx *sdk.Ctx, j *Job) (any, error) {
	// 会话名带触发次数,避免同名会话已存在导致 spawn 失败
	sessName := fmt.Sprintf("cron-%s-%d", j.Name, j.Runs)
	session, err := ctx.AgentSpawn(sdk.SpawnReq{
		Provider:    j.Provider,
		Prompt:      j.Prompt,
		SessionName: sessName,
		Workdir:     j.Workdir,
		Job:         "cron:" + j.Name,
		Labels:      map[string]string{"cron": j.Name, "role": "cron-task"},
		// 交互型:cc 跑完 prompt 后停在会话里等人 attach 续聊;否则跑完即退。
		Interactive: j.Interactive,
	})
	if err != nil {
		return nil, err
	}
	ctx.Logf("任务 %s 已拉起 Agent 会话 %s(interactive=%t)", j.Name, session, j.Interactive)
	return map[string]any{"action": "agent", "session": session, "interactive": j.Interactive}, nil
}

// fireExec 定时跑一条 shell 命令(经 sh -lc,好让 PATH/别名如 cc 解析)。
// 长命令会阻塞调度循环到返回为止(host 侧同步执行,默认 600s 超时);重活请
// 用 action=agent 或缩短命令。失败(exit≠0)时发一条通知让用户看得见。
func fireExec(ctx *sdk.Ctx, j *Job) (any, error) {
	res, err := ctx.CommandExec([]string{"sh", "-lc", j.Command}, 600)
	if err != nil {
		return nil, err
	}
	ctx.Logf("任务 %s 跑命令完成 exit=%d", j.Name, res.Exit)
	// 跑命令是同步的,这里就是「活干完了」:开了通知就报一声,产物与输出末段一并带上
	if j.Notify {
		art, size := expandHome(j.Artifact), int64(0)
		if art != "" {
			size = -1
			if st, err := os.Stat(art); err == nil {
				size = st.Size()
			}
		}
		title, sev := fmt.Sprintf("定时任务 %s 跑完了", j.Name), "info"
		if res.Exit != 0 {
			title, sev = fmt.Sprintf("定时任务 %s 失败(exit=%d)", j.Name, res.Exit), "warning"
		}
		_ = ctx.NotificationPublish(sdk.Notification{
			Type:      "cron.done",
			Severity:  sev,
			Title:     title,
			Body:      doneBody("", nil, art, size, tailStr(strings.TrimRight(res.Output, "\n"), artifactTail)),
			DedupeKey: fmt.Sprintf("cron.done.%s.%d", j.Name, j.Runs),
		})
	}
	// 没开通知的任务只在失败时吭一声——那是「它坏了而你不知道」，不吭声不行
	if res.Exit != 0 && !j.Notify {
		_ = ctx.NotificationPublish(sdk.Notification{
			Type:      "cron.exec",
			Severity:  "warning",
			Title:     fmt.Sprintf("定时命令 %s 失败(exit=%d)", j.Name, res.Exit),
			Body:      tailStr(res.Output, 600),
			DedupeKey: fmt.Sprintf("cron.exec.%s.%d", j.Name, j.Runs),
		})
	}
	return map[string]any{"action": "exec", "exit": res.Exit, "output": res.Output}, nil
}

// tailStr 取字符串末尾至多 n 字节(通知正文只需末段输出)。
func tailStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return "…" + s[len(s)-n:]
}

// ── 校验与展示 ──

// validateAction 校验动作类型及其必填字段。
func validateAction(j Job) error {
	switch j.Action {
	case "agent":
		if strings.TrimSpace(j.Prompt) == "" {
			return fmt.Errorf("action=agent 需要 --prompt <给 Agent 的指令>")
		}
	case "exec":
		if strings.TrimSpace(j.Command) == "" {
			return fmt.Errorf("action=exec 需要 --command <shell 命令>")
		}
	default:
		return fmt.Errorf("action 只能是 agent | exec,得到 %q", j.Action)
	}
	return nil
}

// jobView 是给 CLI/Web 展示的任务视图。除了渲染好的排期/触发时间,还回带原始
// 配置字段(cron/prompt/provider…),好让设置页的「编辑」表单能回填已有配置——
// 否则改个 prompt 都得从头填一遍。schedule 直接给 cron 表达式(前端负责humanize)。
func jobView(j Job) map[string]any {
	v := map[string]any{
		"name":     j.Name,
		"schedule": j.Cron,
		"cron":     j.Cron,
		"action":   j.Action,
		"enabled":  j.Enabled,
		"runs":     j.Runs,
		// 原始可编辑字段(供设置页回填;空值也带上,前端按 action 取用)
		"provider":    j.Provider,
		"prompt":      j.Prompt,
		"workdir":     j.Workdir,
		"interactive": j.Interactive,
		"notify":      j.Notify,
		"artifact":    j.Artifact,
		"command":     j.Command,
	}
	if j.NextRun > 0 {
		v["nextRunAt"] = time.Unix(j.NextRun, 0).Format("2006-01-02 15:04:05")
	}
	if j.LastRun > 0 {
		v["lastRunAt"] = time.Unix(j.LastRun, 0).Format("2006-01-02 15:04:05")
	}
	return v
}

func now() string { return time.Now().Format("15:04:05") }

func nowStr(t time.Time) string { return t.Format("15:04:05") }
