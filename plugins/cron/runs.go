// 执行记录:每次触发落一条,面板上「已触发 3」那个数字才答得出问题。
//
// 「3」本身说不出任何事——哪次跑的、成没成、拉起的是哪个会话、命令输出是什么，
// 全在这里。存法同任务表：整表一个 JSON 数组进插件 KV，新的在前。
package cron

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

const runsKey = "runs"

// 每个任务最多留 30 条、总共最多 300 条。KV 是整表读写的，
// 不设上限的话跑上几个月这张表就变成几兆的 JSON，每次 list 都要整份解析。
const (
	maxRunsPerJob = 30
	maxRunsTotal  = 300
)

// Run 是一次触发的结果。
type Run struct {
	Name    string `json:"name"`
	At      int64  `json:"at"`              // 触发时刻(unix 秒)
	Trigger string `json:"trigger"`         // schedule=到点触发 | manual=手动「立即触发」
	Action  string `json:"action"`          // agent | exec
	OK      bool   `json:"ok"`              // 动作本身有没有成功发起
	Error   string `json:"error,omitempty"` // 失败原因(拉不起会话、命令超时…)

	// action=agent
	Session     string `json:"session,omitempty"`
	Interactive bool   `json:"interactive,omitempty"`
	// action=exec
	Exit   *int   `json:"exit,omitempty"`
	Output string `json:"output,omitempty"` // 只留末段(见 tailStr)

	// 收尾（拉 Agent 的会话退出时补上，见 markDone）
	DoneAt       int64  `json:"doneAt,omitempty"`
	Artifact     string `json:"artifact,omitempty"`
	ArtifactSize int64  `json:"artifactSize,omitempty"`
}

func loadRuns(ctx *sdk.Ctx) ([]Run, error) {
	raw, err := ctx.StorageGet(runsKey)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(raw) == "" {
		return nil, nil
	}
	var runs []Run
	if err := json.Unmarshal([]byte(raw), &runs); err != nil {
		// 记录坏了不该让定时任务本身停摆：丢掉重来，任务表毫发无损
		return nil, nil
	}
	return runs, nil
}

// recordRun 追加一条执行记录并按上限裁剪。
//
// 它**永远不返回错误**：记录只是给人看的，写不进去也不该让这次触发算失败——
// 调用方在 fireJob 里，那时候会话已经拉起来了。
func recordRun(ctx *sdk.Ctx, r Run) {
	runs, err := loadRuns(ctx)
	if err != nil {
		runs = nil
	}
	if b, err := json.Marshal(trimRuns(append([]Run{r}, runs...))); err == nil {
		_ = ctx.StorageSet(runsKey, string(b))
	}
}

// trimRuns 按上限裁剪（新的在前）：每任务 maxRunsPerJob 条、总共 maxRunsTotal 条。
// KV 是整表读写的，不封顶的话跑上几个月这张表会变成几兆的 JSON，每次读都要整份解析。
func trimRuns(runs []Run) []Run {
	perJob := map[string]int{}
	kept := make([]Run, 0, len(runs))
	for _, x := range runs {
		perJob[x.Name]++
		if perJob[x.Name] > maxRunsPerJob || len(kept) >= maxRunsTotal {
			continue
		}
		kept = append(kept, x)
	}
	return kept
}

// withoutJob 滤掉某个任务的全部记录。
func withoutJob(runs []Run, name string) []Run {
	kept := make([]Run, 0, len(runs))
	for _, r := range runs {
		if r.Name != name {
			kept = append(kept, r)
		}
	}
	return kept
}

// dropRuns 删任务时把它的记录一并清掉，否则改名重建会看到前世的记录。
func dropRuns(ctx *sdk.Ctx, name string) {
	runs, err := loadRuns(ctx)
	if err != nil || len(runs) == 0 {
		return
	}
	if b, err := json.Marshal(withoutJob(runs, name)); err == nil {
		_ = ctx.StorageSet(runsKey, string(b))
	}
}

// runsCmd: cron.runs [--name <任务>] [--limit <条数>] —— 查执行记录。
func runsCmd(ctx *sdk.Ctx, args map[string]string) (any, error) {
	name := strings.TrimSpace(args["name"])
	limit := 20
	if v := strings.TrimSpace(args["limit"]); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n <= 0 {
			return nil, fmt.Errorf("--limit 要是正整数,得到 %q", v)
		}
		limit = n
	}
	runs, err := loadRuns(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]map[string]any, 0, limit)
	for _, r := range runs {
		if name != "" && r.Name != name {
			continue
		}
		if len(out) >= limit {
			break
		}
		item := map[string]any{
			"name": r.Name, "at": r.At, "atStr": time.Unix(r.At, 0).Format("2006-01-02 15:04:05"),
			"trigger": r.Trigger, "action": r.Action, "ok": r.OK,
		}
		if r.Error != "" {
			item["error"] = r.Error
		}
		if r.Session != "" {
			item["session"] = r.Session
			item["interactive"] = r.Interactive
		}
		if r.Exit != nil {
			item["exit"] = *r.Exit
		}
		if r.Output != "" {
			item["output"] = r.Output
		}
		if r.DoneAt > 0 {
			item["doneAt"] = r.DoneAt
			item["tookSec"] = r.DoneAt - r.At
		}
		if r.Artifact != "" {
			item["artifact"] = r.Artifact
			item["artifactSize"] = r.ArtifactSize
		}
		out = append(out, item)
	}
	return map[string]any{"count": len(out), "runs": out}, nil
}

// markDone 会话退出时补上收尾信息（用时、产物），并把那条记录挑出来还给调用方。
func markDone(ctx *sdk.Ctx, session string, at int64, artifact string, artifactSize int64) *Run {
	runs, err := loadRuns(ctx)
	if err != nil || len(runs) == 0 {
		return nil
	}
	var hit *Run
	for i := range runs {
		if runs[i].Session == session {
			runs[i].DoneAt = at
			runs[i].Artifact = artifact
			runs[i].ArtifactSize = artifactSize
			hit = &runs[i]
			break // 记录是新的在前，第一条就是最近那次
		}
	}
	if hit == nil {
		return nil
	}
	if b, err := json.Marshal(runs); err == nil {
		_ = ctx.StorageSet(runsKey, string(b))
	}
	cp := *hit
	return &cp
}
