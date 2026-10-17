// Package revive 把「休眠」会话变回活会话。
//
// 机器重启带走 tmux server，但带不走台账：目录、展示名、agent 对话 id 一直都在。
// 所以会话的「在」和「活」是两件事——「在」由台账说了算，「活」由 tmux 说了算。
// 恢复不需要一个时机（开机自启、批量任务、一个要人点的按钮），只需要在
// **用户真的要用它的那一刻**把壳建出来：点开哪个，哪个才起来。
//
// 于是开机的内存成本是 0，而 17 个会话看起来一个都没少。
// 见 docs/design/reliability/session-restore.html。
package revive

import (
	"fmt"
	"os"
	"sync"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// Result 一次恢复的结果。Session 是**新**会话名（新 id），From 是它重开自哪一行。
type Result struct {
	Session string `json:"session"`
	Label   string `json:"label,omitempty"`
	Dir     string `json:"dir,omitempty"`
	From    string `json:"restored_from,omitempty"`
	// Resumed 是接回的 agent 对话 id（空 = 只开了壳）。
	Resumed string `json:"resumed_agent,omitempty"`
	// Reused 表示这一次没有新建：并发的另一个客户端已经把它恢复了，这里直接复用。
	Reused bool `json:"reused,omitempty"`
}

// locks 按**休眠会话 id** 串行化恢复。
//
// 手机和桌面同时点开同一个休眠会话时，两个请求会同时发现「tmux 里没有」并各建一个
// 会话：两个都顶着同一个名字和目录，还都敲 claude --resume 抢同一份 transcript。
// Roami 是单进程，进程内锁就够。
var locks sync.Map // dormant id -> *sync.Mutex

func lockFor(id string) *sync.Mutex {
	m, _ := locks.LoadOrStore(id, &sync.Mutex{})
	return m.(*sync.Mutex)
}

// Candidate 判断一个会话是不是「点开就能恢复」的休眠会话。
//
// 只认 host-restart：**用户显式 kill 掉的会话就该是死的**，它自己在列表里
// 冒出来比消失更让人恼火。这条只约束**自动**恢复；用户在历史面板里明确点
// 「重开」时走 Revive，那是他自己的意思，killed 的也照开。
func Candidate(meta *sessmeta.Store, name string) (sessmeta.Row, bool) {
	row, ok := meta.Get(name)
	if !ok || row.DiedReason != "host-restart" {
		return sessmeta.Row{}, false
	}
	return row, restorable(row)
}

// restorable 目录还在才谈得上重开。worktree 被清是常事——据实报错，
// 别糊里糊涂在别处建一个会话出来。
func restorable(row sessmeta.Row) bool { return row.Status == "dead" && targetDir(row) != "" }

// targetDir 重开该回到哪个目录：**台账目录**。
//
// 后端会把跑进 worktree 的会话在台账里改钉过去（api/session-home-sync.go），所以台账目录
// 就是树上显示它的那个位置。只有台账目录没了（worktree 被清）才退回对话文件自己记的目录。
// 从前是反过来的：对话文件优先——而对话 id 是靠「目录下新冒出来的文件」猜的，猜错一次，
// 恢复就跑到一个八竿子打不着的目录去接一段别人的对话。
func targetDir(row sessmeta.Row) string {
	if d := row.Dir(); d != "" && isDir(d) {
		return d
	}
	if d := agent.ConversationDirFor(row.AgentKind, row.AgentUUID); d != "" && isDir(d) {
		return d
	}
	return ""
}

func isDir(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.IsDir()
}

// ReviveDormant 是**自动**恢复的入口：用户点开一个休眠会话时由 attach 路径调用。
// 只认机器重启带走的那些，其余一律拒绝（让调用方按「会话不存在」处理）。
func ReviveDormant(rt runtime.Runtime, meta *sessmeta.Store, name string) (Result, error) {
	if _, ok := Candidate(meta, name); !ok {
		return Result{}, fmt.Errorf("会话 %s 不是可自动恢复的休眠会话", name)
	}
	return Revive(rt, meta, name)
}

// Revive 是**显式**恢复的入口：按台账重开一个壳，并在有对话 id 时接回原对话。
// 用户主动要求重开，所以 killed 的会话也照开——只要归属目录还在。
//
// 重开的是**壳**不是现场：pane 里的进程死了就是死了。旧行保持 dead、新会话是新 id，
// 「谁是谁的重开」由 restored_from 记着——历史不被改写，也不会重复恢复同一行。
func Revive(rt runtime.Runtime, meta *sessmeta.Store, name string) (Result, error) {
	mu := lockFor(name)
	mu.Lock()
	defer mu.Unlock()

	// 拿到锁后再查一次：等锁的这段时间里，另一个客户端可能已经把它恢复好了。
	// 省掉这一步，并发点击就会建出两个会话（经典的 double-checked locking）。
	if got := meta.RestoredAs(name); got != "" && rt.HasSession(got) {
		row, _ := meta.Get(got)
		return Result{Session: got, Label: row.DisplayLabel(), Dir: row.Dir(), From: name, Reused: true}, nil
	}

	row, ok := meta.Get(name)
	if !ok {
		return Result{}, fmt.Errorf("台账里没有会话 %s", name)
	}
	if row.Status != "dead" {
		return Result{}, fmt.Errorf("会话 %s 还活着，不需要重开", name)
	}
	dir := targetDir(row) // 台账目录还在就回台账目录，否则退回对话文件记的目录；都没了才是真没了
	if dir == "" {
		return Result{}, fmt.Errorf("会话 %s 的目录已不存在：%s", name, row.Dir())
	}

	// 名字**一定要带过去**，而且要落库。
	//
	// 从前这里是 `if row.Label != ""` 才设：没显式改过名的会话（本机 17 个里有 11 个）
	// 于是恢复出来是一串裸 id——而它在休眠列表里明明显示着目录名。同一个会话，
	// 恢复前后两个名字，因为那个名字是显示时现算的、从没进过库。
	// DisplayLabel 把兜底规则收在一处，这里算一次就写进台账，从此它就是真名字。
	label := row.DisplayLabel()
	sess, err := rt.CreateSession(runtime.CreateOpts{Label: label, Dir: dir})
	if err != nil {
		return Result{}, err
	}
	_ = meta.Put(sessmeta.Row{Session: sess, CreatedBy: "revive", InitialCwd: dir})
	_ = meta.SetHome(sess, dir, row.RepoRoot)
	_ = meta.SetLabel(sess, label)
	if row.AgentKind != "" {
		_ = meta.SetAgentKind(sess, row.AgentKind)
	}
	// 先记 restored_from 再敲命令：万一 agent 那一步出岔子，这一行也已经「被恢复过」了，
	// 不会在列表里重新冒出来诱人再点一次。
	_ = meta.SetRestoredFrom(sess, name)
	_ = rt.Tmux("pipe-pane", "-t", "="+sess+":", "-o", "cat >> '"+rt.LogFile(sess)+"'")

	res := Result{Session: sess, Label: label, Dir: dir, From: name}
	if cmd, uuid := resumeCommand(row); cmd != "" {
		// 对话文件自己记的目录和重开的目录对不上：这段对话不是这个目录里的，不接——
		// 接了就是拿别处的记忆冒充这里的。壳照开，人要接可以自己 claude --resume
		if cd := agent.ConversationDirFor(row.AgentKind, uuid); cd != "" && cd != dir {
			return res, nil
		}
		// 只把命令**填在命令行上**，不替人回车：接不接、什么时候接由人定——
		// 一次点开十几个会话同时 resume 会把机器卡住，而且有的只是想看看目录
		_ = meta.SetAgentSession(sess, uuid)
		_ = rt.Tmux("send-keys", "-t", "="+sess+":", cmd)
		res.Resumed = uuid
	}
	return res, nil
}

// resumeCommand 给出「接回原对话」要在 shell 里敲的命令（没有就返回空串）。
//
// 每一型 agent 自己说自己怎么接回（internal/agent）。从前这里硬编着
// `claude --resume`，codex 直接跳过——而 codex 早就支持 `codex resume <id>` 了，
// 那句「codex 没有对应参数」在写下时是对的，之后没人回头改。
// 现在新增一型只要实现 agent.Agent 并 Register，这条路自动认得它。
func resumeCommand(row sessmeta.Row) (cmd, uuid string) {
	if row.AgentUUID == "" {
		return "", ""
	}
	kind := row.AgentKind
	if kind == "" {
		// 老数据没记类型。**不猜**：猜错就是拿这一型的 id 去喂另一型，
		// 敲出一条跑得起来但接错对话的命令，比不敲更糟。
		return "", ""
	}
	if c := agent.ResumeCommandFor(kind, row.AgentUUID); c != "" {
		return c, row.AgentUUID
	}
	return "", ""
}
