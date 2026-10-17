// 跑完通知：任务真正结束时，把「跑完了没、跑了多久、产物在哪」推到通知流。
//
// 为什么要专门有这一层：`cron.tick` 拉起 Agent 会话就返回了——**触发成功不等于活干完了**。
// 一条凌晨两点的自检跑四十分钟，人第二天早上想知道的是「跑完没、结果在哪」，
// 而不是「两点整触发过」。会话在 spawn 时就登记给了本插件（host 侧 AddSession），
// plugind 会在它退出时派 session:agent.exited 事件过来，收尾就挂在那儿。
//
// 通知发到 Roam 的通知流；装了 IM 插件并「绑定通知」的话，它作为 sink 会把同一条
// 渲染成飞书卡片——所以这里不直接调 IM，也不该知道 IM 存在。
package cron

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

// 产物贴进通知的末段上限：卡片不是日志窗，超了只会把「跑完了」这句话挤下去
const artifactTail = 700

func onAgentExited(ctx *sdk.Ctx, payload json.RawMessage) error {
	var ev struct {
		Session string            `json:"session"`
		Job     string            `json:"job"`
		Labels  map[string]string `json:"labels"`
	}
	if err := json.Unmarshal(payload, &ev); err != nil {
		return err
	}
	name := ev.Labels["cron"]
	if name == "" {
		name = strings.TrimPrefix(ev.Job, "cron:")
	}
	if name == "" {
		return nil // 不是我拉起来的
	}

	jobs, err := loadJobs(ctx)
	if err != nil {
		return err
	}
	var job *Job
	for i := range jobs {
		if jobs[i].Name == name {
			job = &jobs[i]
			break
		}
	}

	art, size := "", int64(0)
	if job != nil && job.Artifact != "" {
		art = expandHome(job.Artifact)
		if st, err := os.Stat(art); err == nil {
			size = st.Size()
		} else {
			size = -1 // 说好了会产出，结果没有——通知里要说清楚
		}
	}
	run := markDone(ctx, ev.Session, time.Now().Unix(), art, size)

	// 没开「跑完通知我」的任务只记账、不打扰
	if job == nil || !job.Notify {
		return nil
	}
	body := doneBody(ev.Session, run, art, size, readTail(art, artifactTail))
	return ctx.NotificationPublish(sdk.Notification{
		Type:      "cron.done",
		Severity:  "info",
		Title:     fmt.Sprintf("定时任务 %s 跑完了", name),
		Body:      body,
		DedupeKey: "cron.done." + ev.Session,
	})
}

// doneBody 拼通知正文：会话、用时、产物（有就带上大小与末段）。
// 抽成纯函数是为了能测——通知的正文是这条功能唯一交付给人的东西。
func doneBody(session string, run *Run, artifact string, size int64, tail string) string {
	var b strings.Builder
	if session != "" {
		fmt.Fprintf(&b, "会话 %s", session)
	}
	if run != nil && run.DoneAt > run.At {
		fmt.Fprintf(&b, " · 用时 %s", fmtDur(run.DoneAt-run.At))
	}
	if artifact != "" {
		if b.Len() > 0 {
			b.WriteString("\n")
		}
		switch {
		case size < 0:
			fmt.Fprintf(&b, "产物 %s（没找到——任务可能没写出来）", artifact)
		default:
			fmt.Fprintf(&b, "产物 %s（%s）", artifact, fmtSize(size))
		}
	}
	if tail != "" {
		if b.Len() > 0 {
			b.WriteString("\n\n")
		}
		b.WriteString(tail)
	}
	return strings.TrimSpace(b.String())
}

func fmtDur(sec int64) string {
	switch {
	case sec < 60:
		return fmt.Sprintf("%d 秒", sec)
	case sec < 3600:
		return fmt.Sprintf("%d 分钟", sec/60)
	default:
		return fmt.Sprintf("%d 小时 %d 分钟", sec/3600, (sec%3600)/60)
	}
}

func fmtSize(n int64) string {
	switch {
	case n < 1024:
		return fmt.Sprintf("%d B", n)
	case n < 1024*1024:
		return fmt.Sprintf("%.1f KB", float64(n)/1024)
	default:
		return fmt.Sprintf("%.1f MB", float64(n)/(1024*1024))
	}
}

// expandHome 把 ~ 展开：任务是人在表单里填的，`~/.roami/selftest/x.md` 是最自然的写法。
func expandHome(p string) string {
	if !strings.HasPrefix(p, "~/") {
		return p
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return p
	}
	return home + p[1:]
}

// readTail 读产物末尾若干字节。读不到就返回空——产物只是通知里的添头，
// 不该因为文件权限或还没写完让整条通知发不出去。
func readTail(path string, n int) string {
	if path == "" {
		return ""
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return tailStr(strings.TrimRight(string(b), "\n"), n)
}
