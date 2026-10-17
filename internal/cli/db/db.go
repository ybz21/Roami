// Package db 是 meta.db 的运维入口：看状态、显式跑迁移、落备份、改会话归属。
//
// 结构性迁移本身不靠这些命令——metadb.Open 里就做完了，任何代码路径都拿不到
// 未迁移的库。这里存在的意义是**可观测**（停在哪一版、各表多少行）与**可显式触发**
// （旧台账收编要 DataDir，某些入口开库时给不全，用 migrate 补一刀）。
package db

import (
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strconv"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/revive"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/storage"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// Run 分发 `roami session db <子命令>`。
func Run(rt runtime.Runtime, args []string, w io.Writer) error {
	sub := "status"
	if len(args) > 0 {
		sub = args[0]
		args = args[1:]
	}
	asJSON := false
	var rest []string
	for _, a := range args {
		if a == "--json" {
			asJSON = true
			continue
		}
		rest = append(rest, a)
	}
	switch sub {
	case "status":
		return status(rt, asJSON, w)
	case "migrate":
		return migrate(rt, asJSON, w)
	case "backup":
		return backup(rt, rest, asJSON, w)
	case "set-home":
		return setHome(rt, rest, w)
	case "history":
		return history(rt, rest, asJSON, w)
	case "link-agent":
		return linkAgent(rt, rest, w)
	case "restore":
		return restore(rt, rest, asJSON, w)
	case "revive":
		return reviveDormant(rt, rest, asJSON, w)
	default:
		return fmt.Errorf("未知子命令 %q（可用：status | migrate | backup | history | restore | revive | set-home | link-agent）", sub)
	}
}

func open(rt runtime.Runtime) (*metadb.DB, error) {
	return metadb.Open(rt.HomeDir, metadb.Options{
		DataDir: rt.DataDir, HomeDir: rt.HomeDir, Now: rt.Now,
	})
}

// Info 是 `db status --json` 的输出。**后端靠它握手**：库的路径只能从这里拿，
// 绝不能由后端自己 filepath.Join —— ROAM_DATA 与 ROAM_HOME 可以指到不同地方，
// 自己拼会静悄悄开出一个空库。
type Info struct {
	Path      string         `json:"path"`
	Version   int            `json:"schemaVersion"`
	MinCompat int            `json:"minCompatible"`
	Journal   string         `json:"journalMode"`
	CLI       string         `json:"cliVersion"`
	Rows      map[string]int `json:"rows,omitempty"`
}

// minCompatible 是「读得懂本库的最低后端版本」。schema 只增不改，所以老读者
// 永远读得懂新库；真出现破坏性变更时把这个数字顶上去，后端会自己退到只读。
const minCompatible = 1

var countedTables = []string{
	"sessions", "projects", "project_aliases", "races", "session_homes",
	"swarms", "swarm_members", "swarm_cards", "plugin_sessions", "tmux_epochs",
}

func status(rt runtime.Runtime, asJSON bool, w io.Writer) error {
	d, err := open(rt)
	if err != nil {
		return err
	}
	v, err := d.Version()
	if err != nil {
		return err
	}
	var journal string
	_ = d.QueryRow(`PRAGMA journal_mode`).Scan(&journal)

	info := Info{Path: d.Path(), Version: v, MinCompat: minCompatible,
		Journal: journal, CLI: runtime.Version, Rows: map[string]int{}}
	for _, t := range countedTables {
		var n int
		if d.QueryRow(`SELECT COUNT(*) FROM `+t).Scan(&n) == nil {
			info.Rows[t] = n
		}
	}
	if asJSON {
		return json.NewEncoder(w).Encode(info)
	}
	fmt.Fprintf(w, "\n  %s %s\n", ui.Bold("库"), info.Path)
	fmt.Fprintf(w, "  %s schema v%d · journal %s\n\n", ui.Bold("版本"), v, journal)
	names := make([]string, 0, len(info.Rows))
	for t := range info.Rows {
		names = append(names, t)
	}
	sort.Strings(names)
	for _, t := range names {
		fmt.Fprintf(w, "    %-18s %d\n", t, info.Rows[t])
	}
	fmt.Fprintln(w)
	return nil
}

func migrate(rt runtime.Runtime, asJSON bool, w io.Writer) error {
	d, err := open(rt)
	if err != nil {
		return err
	}
	v, _ := d.Version()
	rep := metadb.LastReport()
	if asJSON {
		return json.NewEncoder(w).Encode(map[string]any{
			"schemaVersion": v, "report": rep,
		})
	}
	ui.Ok(w, "schema 已在 v%d", v)
	if rep.Projects+rep.Races+rep.Homes+rep.Members+rep.Cards > 0 {
		ui.Info(w, "收编：%s", rep)
	}
	for _, sid := range rep.SkippedSwarms {
		ui.Warn(w, "跳过孤儿蜂群目录 %s（swarms 表里没有登记）", sid)
	}
	return nil
}

// history 列出已结束的会话。这是「重启后还能找回那天下午干了什么」的读口：
// 日志还躺在 logs/<id>.log，这张表是找回它们的唯一索引。
func history(rt runtime.Runtime, rest []string, asJSON bool, w io.Writer) error {
	limit := 200
	for i, a := range rest {
		if a == "--limit" && i+1 < len(rest) {
			if n, err := strconv.Atoi(rest[i+1]); err == nil && n > 0 {
				limit = n
			}
		}
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	rows := meta.History(limit)
	if asJSON {
		if rows == nil {
			rows = []sessmeta.Row{}
		}
		return json.NewEncoder(w).Encode(rows)
	}
	if len(rows) == 0 {
		ui.Info(w, "没有已结束的会话")
		return nil
	}
	fmt.Fprintln(w)
	for _, r := range rows {
		name := r.Label
		if name == "" {
			name = r.Session
		}
		fmt.Fprintf(w, "   %s %s  %s  %s\n", ui.IconSession, ui.Bold(name),
			ui.Dim(r.DiedAt), ui.Dim(r.Home))
	}
	fmt.Fprintf(w, "\n   共 %d 个已结束会话\n\n", len(rows))
	return nil
}

// restore 按台账把一个已结束的会话**重新开一个壳**：同目录、同展示名，
// 有 agent 对话 id 就顺带 `claude --resume` 接回原对话。
//
// 实现共用 internal/revive —— Web 那边点开一个休眠会话走的是同一段代码。
// 抄第二份必然走散，就像 AGENTS.md 开头说的那件事。
func restore(rt runtime.Runtime, rest []string, asJSON bool, w io.Writer) error {
	if len(rest) < 1 {
		return fmt.Errorf("用法：roami session db restore <会话id> [--json]")
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	res, err := revive.Revive(rt, meta, rest[0])
	if err != nil {
		return err
	}
	if asJSON {
		return json.NewEncoder(w).Encode(map[string]string{
			"session": res.Session, "label": orSelf(res.Label, res.Session), "dir": res.Dir,
			"restoredFrom": res.From, "resumedAgent": res.Resumed,
		})
	}
	ui.Ok(w, "已重开 %s → %s", ui.Bold(res.From), ui.Bold(res.Session))
	if res.Resumed != "" {
		ui.Info(w, "已接回原对话 %s", ui.Dim(res.Resumed))
	}
	return nil
}

// reviveDormant 是**自动**恢复的入口：后端在 attach 一个 tmux 里不存在的会话时调它。
// 与 restore 的区别只有一条——只认「机器重启带走的」，显式 kill 掉的不会自己回来。
func reviveDormant(rt runtime.Runtime, rest []string, asJSON bool, w io.Writer) error {
	if len(rest) < 1 {
		return fmt.Errorf("用法：roami session db revive <会话id> [--json]")
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	res, err := revive.ReviveDormant(rt, meta, rest[0])
	if err != nil {
		return err
	}
	if asJSON {
		return json.NewEncoder(w).Encode(res)
	}
	ui.Ok(w, "已恢复 %s → %s", ui.Bold(res.From), ui.Bold(res.Session))
	return nil
}

func backup(rt runtime.Runtime, rest []string, asJSON bool, w io.Writer) error {
	dest := ""
	for i, a := range rest {
		if a == "--out" && i+1 < len(rest) {
			dest = rest[i+1]
		}
	}
	d, err := open(rt)
	if err != nil {
		return err
	}
	path, err := d.Backup(dest)
	if err != nil {
		return err
	}
	if asJSON {
		return json.NewEncoder(w).Encode(map[string]string{"path": path})
	}
	ui.Ok(w, "已备份到 %s", ui.Bold(path))
	return nil
}

// linkAgent 把会话和它那段 agent 对话（Claude Code 的 <uuid>.jsonl）关联起来。
//
// ttmux 自己拉起的 agent 靠 --session-id，关联由构造保证；用户在会话里手敲
// `claude` 的那些只能由上层推断，所以这里**只记一次不覆盖**——先前确定下来的
// 那次比后来推断的更可信。
//
// 第三个参数是 agent 类型。恢复时靠它决定敲哪一型的命令，而且**不猜**——
// 从前这条路只记 id 不记类型，于是手敲 claude 的会话即便认到了对话，
// 重开出来也永远只有壳。
func linkAgent(rt runtime.Runtime, rest []string, w io.Writer) error {
	if len(rest) < 2 {
		return fmt.Errorf("用法：roami session db link-agent <会话> <对话uuid> [类型]")
	}
	sess := rt.Resolve(rest[0])
	if sess == "" {
		sess = rest[0]
	}
	kind := ""
	if len(rest) >= 3 {
		if agent.Get(rest[2]) == nil {
			return fmt.Errorf("未知的 agent 类型 %q（可用：%v）", rest[2], agent.Kinds())
		}
		kind = agent.Get(rest[2]).Kind()
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	if err := meta.SetAgentSession(sess, rest[1]); err != nil {
		return err
	}
	return meta.SetAgentKind(sess, kind)
}

// setHome 记会话归属的**台账事实**。后端事后改钉（cdInto 之后、fork 继承父归属）
// 走这里，因为 sessions 表归 CLI 写——后端自己那张 session_homes 只管运行时绑定。
func setHome(rt runtime.Runtime, rest []string, w io.Writer) error {
	if len(rest) < 2 {
		return fmt.Errorf("用法：roami session db set-home <会话> <目录>")
	}
	sess := rt.Resolve(rest[0])
	if sess == "" {
		sess = rest[0] // 会话可能已经没了，台账照记
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	return meta.SetHome(sess, rest[1], "")
}

// orSelf 展示名为空时退回会话自己的 id。
func orSelf(label, sess string) string {
	if label == "" {
		return sess
	}
	return label
}
