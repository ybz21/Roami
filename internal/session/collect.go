package session

import (
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/memalert"
	"github.com/ybz21/Roami/internal/memguard"
	"github.com/ybz21/Roami/internal/memthrottle"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/storage"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// 会话集合的**唯一出处**。
//
// 从前 `ls --json`（ListJSON）和 `ls --tree`（buildTree）各自跑一遍 list-sessions、
// 各自解析同样那 8 个字段。加一类新会话就得在两处都补一遍，漏一处就是「概览里有、
// 点进项目又没了」——用户看到的数据不一致，根子在这儿。
//
// 现在两个出口都基于 Collect，休眠会话只在这里合并一次。
// 见 docs/design/reliability/session-restore.html。

// sessionListFormat 一次问齐列表要用的字段。两个出口共用同一份格式串，
// 免得字段顺序在两边悄悄分叉。
const sessionListFormat = "#{session_name}\t#{session_windows}\t#{session_created}\t" +
	"#{session_attached}\t#{session_activity}\t#{window_activity}\t#{session_id}\t#{" + runtime.LabelOption + "}"

// Collect 返回本机所有会话：tmux 里活着的，加上台账里**休眠**的
// （机器重启带走了 tmux 那一半，点开即恢复）。
//
// 顺带做一次 Reconcile：这是台账收敛「谁还活着」的地方，而列会话正是最自然的时机。
func Collect(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool) []sessionInfo {
	out, err := rt.TmuxOutput("list-sessions", "-F", sessionListFormat)
	live := []sessionInfo{}
	if err == nil {
		live = parseSessionLines(out, exclude)
	}
	// server 确定不在（socket 连不上）≠ 盲态：前者台账里所有活行一起进历史，
	// 后者一行不动。分不开这两种，重启后休眠会话就要等下一次建会话才出现。
	serverGone := err != nil && runtime.NoServer(out)
	// 内存画像：会话列表上那条内存条的数据源。cgroup 按 pane 分好了，
	// 一次读两个文件，比轮询 ps 聚合整棵进程树便宜也准（含子进程全部后代）。
	samples := make([]memalert.Sample, 0, len(live))
	brakes := make([]memthrottle.Sample, 0, len(live))
	for i := range live {
		m := sampleMem(rt, live[i].Name)
		if !m.OK {
			continue
		}
		live[i].Mem = &memInfo{Cur: m.Cur, Peak: m.Peak, Limit: m.Limit}
		samples = append(samples, memalert.Sample{
			Session: live[i].Name, Label: live[i].Label,
			Cur: m.Cur, Peak: m.Peak, Limit: m.Limit, OOMKills: m.OOMKills,
		})
		brakes = append(brakes, memthrottle.Sample{
			Session: live[i].Name, Label: live[i].Label,
			PIDs: m.PIDs, Cur: m.Cur, Swap: m.Swap, High: m.High, Max: m.Limit,
		})
	}
	// tmux 盲态（list-sessions 出错但不是「server 不在」）时 alive 为空，
	// Reconcile 内部会一行不动——「看不见的时候不下判断」。这里照常调用，让它自己决定。
	if meta != nil {
		if serverGone {
			meta.ReconcileServerGone()
		} else {
			alive := make(map[string]bool, len(live))
			for _, s := range live {
				alive[s.Name] = true
			}
			// 把「这个会话吃了多少内存」接给台账。cgroup 按 pane 分好了，
			// 一次读两个文件，比轮询 ps 聚合整棵进程树便宜也准。
			meta.MemStat = func(sess string) (int64, int64, bool) { return sessionMem(rt, sess) }
			meta.Reconcile(alive)
		}
		// 看门狗：逼近上限 / 撞顶被杀各说一次。列会话本来就在采内存，顺手判一下，
		// 不必再养一个采集器（这也是它没做成 hostmonitor 插件的原因——
		// 数据跟着会话列表走，插件那条路要再建一条通路）。
		if db, err := metadb.Open(rt.HomeDir, metadb.Options{DataDir: rt.DataDir}); err == nil {
			memalert.Check(db, rt.Now(), samples)
			// 总量闸（L2）：每个会话都守着自己的上限、加起来仍然把机器压垮的那一档。
			// 稳态下 Plan 返回空（压过/踩过的会话下一轮就认得出来），不花额外开销。
			room := memthrottle.ProbeSwapRoom()
			host := memthrottle.Host{
				Total: memguard.TotalMemory(), Avail: memguard.AvailableMemory(),
				SwapFree: room.Free, Compressed: room.Compressed,
			}
			th := memthrottle.FromEnv()
			for _, d := range memthrottle.Apply(memthrottle.Plan(host, th, brakes), memthrottle.Cgroup()) {
				if d.Reclaim > 0 {
					memalert.Compressed(db, rt.Now(), d.Session, d.Label, d.Reclaim)
					continue
				}
				memalert.Throttled(db, rt.Now(), d.Session, d.Label, d.High, d.Brake)
			}
			// 该动手却没落点：这一层自己解决不了（开 zram 要 root），只能让人知道。
			if memthrottle.Stalled(host, th, brakes) {
				memalert.NoSwapRoom(db, rt.Now(), room.Compressed)
			}
		}
	}
	return appendDormant(live, meta, exclude)
}

// memSample 一个会话此刻的内存画像。
//
// 一个会话可能有多个 pane，各在自己的 scope 里：当前用量求和（整个会话吃了多少），
// 峰值取最大的那个（谁涨谁是主因），OOM 次数求和（任一 pane 撞顶都算它撞了顶）。
// 上限取最大的那个——多 pane 时各自有各自的天花板，展示按最宽的算。
type memSample struct {
	Cur, Peak, Limit, OOMKills int64
	Swap                       int64 // 已经挤到交换区的量（总量闸靠它认出这一轮压过没有）
	High                       int64 // 当前软限（总量闸靠它认出谁已经踩着刹车）
	PIDs                       []int
	OK                         bool
}

func sampleMem(rt runtime.Runtime, sess string) memSample {
	var m memSample
	for _, pid := range rt.PanePIDs(sess) {
		m.PIDs = append(m.PIDs, pid)
		if c, p, got := memguard.Current(pid); got {
			m.OK = true
			m.Cur += c
			if p > m.Peak {
				m.Peak = p
			}
		}
		if l := memguard.Limit(pid); l > m.Limit {
			m.Limit = l
		}
		// 交换区用量求和：一个会话多个 pane，压出去多少是它们的总和。
		if sw, ok := memguard.SwapOf(pid); ok {
			m.Swap += sw
		}
		// 软限取**最小**的那个：多 pane 时只要有一个被压过，这个会话就是踩着刹车的。
		// 取最大会让「踩了一个 pane」看起来像没踩，下一轮又去踩一次，越踩越低。
		if h, ok := memguard.HighOf(pid); ok && h > 0 && (m.High == 0 || h < m.High) {
			m.High = h
		}
		m.OOMKills += memguard.OOMKilled(pid)
	}
	return m
}

// sessionMem 供 sessmeta.Reconcile 落台账用（峰值 + OOM 次数）。
func sessionMem(rt runtime.Runtime, sess string) (peak, ooms int64, ok bool) {
	m := sampleMem(rt, sess)
	return m.Peak, m.OOMKills, m.OK
}

// parseSessionLines 解析 list-sessions 的输出。
func parseSessionLines(out string, exclude map[string]bool) []sessionInfo {
	sessions := []sessionInfo{}
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		parts := strings.Split(line, "\t")
		if len(parts) < 4 || exclude[parts[0]] {
			continue
		}
		windows, _ := strconv.Atoi(parts[1])
		attached, _ := strconv.Atoi(parts[3])
		lastActivity := ""
		if len(parts) > 4 {
			lastActivity = parts[4]
		}
		if len(parts) > 5 {
			// window_activity 补 session_activity 的盲区：tmux 只在 attach/输入/焦点变化时
			// 刷新 session_activity，后台无人 attach 的会话即便一直有输出（agent 干活）也不动。
			lastActivity = maxNumeric(lastActivity, parts[5])
		}
		tmuxID := ""
		if len(parts) > 6 {
			tmuxID = parts[6]
		}
		label := ""
		if len(parts) > 7 {
			label = strings.TrimSpace(parts[7])
		}
		created, _ := strconv.ParseInt(parts[2], 10, 64)
		row := runtime.SessionRow{Name: parts[0], Label: label, TmuxID: tmuxID, Created: created}
		sessions = append(sessions, sessionInfo{
			Name:         row.Name,
			Label:        row.DisplayLabel(),
			ID:           row.ID(),
			TmuxID:       tmuxID,
			Windows:      windows,
			Created:      parts[2],
			Attached:     attached,
			LastActivity: lastActivity,
			State:        "live",
		})
	}
	return sessions
}

// appendDormant 把「机器重启带走、但点开就能回来」的会话并进列表。
//
// 会话的「在」由台账说了算，「活」由 tmux 说了算；列表要显示的是「在」的全集。
// 少了这一步，前端 App.tsx 的 dropDeadTokens 会按这份 id 表把上次开着的终端标签
// 全部丢掉——用户连点击的机会都没有，更谈不上懒恢复。
func appendDormant(sessions []sessionInfo, meta *sessmeta.Store, exclude map[string]bool) []sessionInfo {
	if meta == nil {
		return sessions
	}
	live := make(map[string]bool, len(sessions))
	for _, s := range sessions {
		live[s.Name] = true
	}
	for _, r := range meta.Dormant() {
		if live[r.Session] || exclude[r.Session] {
			continue
		}
		dir := r.Dir()
		sessions = append(sessions, sessionInfo{
			Name:         r.Session,
			Label:        r.DisplayLabel(),
			ID:           r.Session,
			Created:      r.CreatedAt,
			LastActivity: r.DiedAt,
			State:        "dormant",
			Agent:        r.AgentKind,
			// 能不能接回对话，由那一型自己说了算——别在这里硬判 kind。
			Resumable: agent.ResumeCommandFor(r.AgentKind, r.AgentUUID) != "",
			Dir:       dir,
			Repo:      r.RepoRoot,
			CreatedBy: r.CreatedBy,
			Parent:    r.Parent,
		})
	}
	return sessions
}
