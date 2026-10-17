package metadb

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/ybz21/Roami/internal/id"
)

// 一次性收编：把 Roami 后端那三个散装 JSON 台账、以及每群 swarm.db 里的
// members / cards，搬进主库。
//
// **盲态口径**：本步骤不问 tmux。session-homes.json 自带会话名快照，够用了。
// runtime 那条「tmux 盲态就整个不做也不写标记」的纪律只适用于**会改动 tmux 自身**的
// 迁移（改会话名）；这里一个 tmux 状态都不碰，照做即可，判错了由 Reconcile 自愈。
// 下一个人别照着 runtime 那条抄。
//
// **只增不覆盖**：全程 INSERT OR IGNORE + UPDATE ... WHERE 该列还空着。
// 重复跑一遍不会推翻用户在新库里改过的任何东西。

// errNoDataDir 让这一步不盖章：plugind 之类的入口可能先开库而没带 DataDir，
// 那就等下一次带全 Options 的 Open 再补。因此 import 必须是**最后一步**，
// 前面的 step 都不依赖 Options。
var errNoDataDir = fmt.Errorf("缺 DataDir，跳过旧台账收编: %w", ErrStepDeferred)

// Report 说明这次收编搬了什么，给 `roami db migrate` 打印、也进测试断言。
type Report struct {
	Projects, Aliases, Races, Homes, Members, Cards, Traces int
	// SkippedSwarms 是磁盘上有目录、swarms 表里却没有登记的孤儿群。
	SkippedSwarms []string
}

func (r Report) String() string {
	s := fmt.Sprintf("项目 %d · 别名 %d · 竞赛 %d · 会话归属 %d · 蜂群成员 %d · 卡片 %d · 留痕 %d",
		r.Projects, r.Aliases, r.Races, r.Homes, r.Members, r.Cards, r.Traces)
	if len(r.SkippedSwarms) > 0 {
		s += fmt.Sprintf("（跳过 %d 个孤儿蜂群目录）", len(r.SkippedSwarms))
	}
	return s
}

// lastReport 供 `roami db migrate` 取回刚才那次收编的结果。
var lastReport Report

func LastReport() Report { return lastReport }

func importLegacy(tx *sql.Tx, opt Options) error {
	if opt.DataDir == "" {
		return errNoDataDir
	}
	var rep Report
	if err := importProjects(tx, opt, &rep); err != nil {
		return err
	}
	if err := importRaces(tx, opt, &rep); err != nil {
		return err
	}
	if err := importSessionHomes(tx, opt, &rep); err != nil {
		return err
	}
	if err := importSwarmDetail(tx, opt, &rep); err != nil {
		return err
	}
	lastReport = rep
	return nil
}

// readJSON 读一个可选的台账文件。文件不在 = 这台机器就没有过，不是错误。
func readJSON(path string, v any) (bool, error) {
	b, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if len(b) == 0 {
		return false, nil
	}
	if err := json.Unmarshal(b, v); err != nil {
		// 台账坏了不该让整个迁移卡住：记一笔，当作没有。
		fmt.Fprintf(os.Stderr, "ttmux: %s 解析失败，跳过: %v\n", filepath.Base(path), err)
		return false, nil
	}
	return true, nil
}

// ── projects.json ───────────────────────────────────────────────────────

type legacyProject struct {
	ID            string `json:"id"`
	Dir           string `json:"dir"`
	Origin        string `json:"origin"`
	Pinned        bool   `json:"pinned"`
	DisplayName   string `json:"displayName"`
	DefaultAgent  string `json:"defaultAgent"`
	DefaultBase   string `json:"defaultBase"`
	FirstSeen     int64  `json:"firstSeen"`
	LastSeen      int64  `json:"lastSeen"`
	LastSessionAt int64  `json:"lastSessionAt"`
}

type legacyProjectFile struct {
	Repos   map[string]*legacyProject `json:"repos"`
	Aliases map[string]string         `json:"aliases"`
}

func importProjects(tx *sql.Tx, opt Options, rep *Report) error {
	var f legacyProjectFile
	ok, err := readJSON(filepath.Join(opt.DataDir, "projects.json"), &f)
	if err != nil || !ok {
		return err
	}
	keys := make([]string, 0, len(f.Repos))
	for k := range f.Repos {
		keys = append(keys, k)
	}
	// 定序：同目录的重复条目谁留下不能随 map 迭代序漂。
	sort.Strings(keys)
	for _, key := range keys {
		e := f.Repos[key]
		if e == nil || e.Dir == "" {
			continue
		}
		pid := key
		if !id.Valid(key) || e.ID != key { // v1 老 key（目录名 slug + 路径 hash）
			pid = id.NewAt(opt.now())
		}
		res, err := tx.Exec(`INSERT OR IGNORE INTO projects
			(id,dir,origin,display_name,pinned,default_agent,default_base,
			 first_seen,last_seen,last_session_at)
			VALUES(?,?,?,?,?,?,?,?,?,?)`,
			pid, e.Dir, e.Origin, e.DisplayName, boolInt(e.Pinned),
			e.DefaultAgent, e.DefaultBase, e.FirstSeen, e.LastSeen, e.LastSessionAt)
		if err != nil {
			return err
		}
		if n, _ := res.RowsAffected(); n > 0 {
			rep.Projects++
		}
		if pid != key { // 老 key 留作别名，老书签 #/projects/<老key> 不失效
			if err := putAlias(tx, key, pid, rep); err != nil {
				return err
			}
		}
	}
	for alias, target := range f.Aliases {
		if err := putAlias(tx, alias, target, rep); err != nil {
			return err
		}
	}
	return nil
}

// putAlias 只在目标项目确实在册时落别名——FK 会挡下悬空的，与其让整个事务失败，
// 不如安静跳过（老文件里本来就可能留着指向已删项目的别名）。
func putAlias(tx *sql.Tx, alias, projectID string, rep *Report) error {
	res, err := tx.Exec(`INSERT OR IGNORE INTO project_aliases(alias,project_id)
		SELECT ?, id FROM projects WHERE id=?`, alias, projectID)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n > 0 {
		rep.Aliases++
	}
	return nil
}

func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// ── races.json ──────────────────────────────────────────────────────────

type legacyRace struct {
	ID          string            `json:"id"`
	LegacyID    string            `json:"legacyId"`
	Name        string            `json:"name"`
	Dir         string            `json:"dir"`
	Base        string            `json:"base"`
	Prompt      string            `json:"prompt"`
	CreatedAt   string            `json:"createdAt"`
	Status      string            `json:"status"`
	Winner      string            `json:"winner"`
	CrownDone   []string          `json:"crownDone"`
	Contestants []json.RawMessage `json:"contestants"`
}

func importRaces(tx *sql.Tx, opt Options, rep *Report) error {
	var all []legacyRace
	ok, err := readJSON(filepath.Join(opt.DataDir, "races.json"), &all)
	if err != nil || !ok {
		return err
	}
	for _, r := range all {
		if r.ID == "" {
			continue
		}
		done, _ := json.Marshal(r.CrownDone)
		cts, _ := json.Marshal(r.Contestants)
		res, err := tx.Exec(`INSERT OR IGNORE INTO races
			(id,legacy_id,name,dir,base,prompt,created_at,status,winner,crown_done,contestants)
			VALUES(?,?,?,?,?,?,?,?,?,?,?)`,
			r.ID, r.LegacyID, r.Name, r.Dir, r.Base, r.Prompt, r.CreatedAt,
			r.Status, r.Winner, string(done), string(cts))
		if err != nil {
			return err
		}
		if n, _ := res.RowsAffected(); n > 0 {
			rep.Races++
		}
	}
	return nil
}

// ── session-homes.json ──────────────────────────────────────────────────

type legacyHomeRow struct {
	Home string `json:"home"`
	Name string `json:"name"`
}

type legacyHomeFile struct {
	V     int                      `json:"v"`
	Homes map[string]legacyHomeRow `json:"homes"`
}

// importSessionHomes 把一份数据导进**两处**，因为它混装了寿命完全不同的两种东西：
//
//   - 运行时绑定（键是 tmux $N，pane 一死就收敛）→ session_homes 表
//   - 台账事实（键是持久会话 id，会话死了也要留）→ sessions.home_dir
//
// 后端拥有前者、CLI 拥有后者，单写者约定因此完整保留。
func importSessionHomes(tx *sql.Tx, opt Options, rep *Report) error {
	path := filepath.Join(opt.DataDir, "session-homes.json")
	var f legacyHomeFile
	ok, err := readJSON(path, &f)
	if err != nil {
		return err
	}
	if ok && f.Homes != nil {
		for tmuxID, row := range f.Homes {
			if err := adoptHome(tx, tmuxID, row.Name, row.Home, opt, rep); err != nil {
				return err
			}
		}
		return nil
	}
	// v1 形态：裸 map[会话名]目录，没有 $N。只有台账事实那一半可搬。
	var v1 map[string]string
	if ok2, _ := readJSON(path, &v1); ok2 {
		for name, home := range v1 {
			if err := adoptHome(tx, "", name, home, opt, rep); err != nil {
				return err
			}
		}
	}
	return nil
}

func adoptHome(tx *sql.Tx, tmuxID, name, home string, opt Options, rep *Report) error {
	if home == "" {
		return nil
	}
	if tmuxID != "" {
		if _, err := tx.Exec(`INSERT OR IGNORE INTO session_homes(tmux_id,epoch,name,home,pinned_at)
			VALUES(?,NULL,?,?,?)`, tmuxID, name, home, opt.now().Unix()); err != nil {
			return err
		}
		rep.Homes++
	}
	if name == "" {
		return nil // 连会话名都没有：认领不到台账那一半
	}
	res, err := tx.Exec(`UPDATE sessions SET home_dir=? WHERE id=? AND IFNULL(home_dir,'')=''`, home, name)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n > 0 {
		return nil
	}
	// 台账里没有这个会话：宁可留一行 dead 记录，也不丢掉「它存在过、在这个目录」这个事实。
	now := rfc3339(opt.now())
	_, err = tx.Exec(`INSERT OR IGNORE INTO sessions
		(id,created_by,created_at,home_dir,status,died_at,died_reason)
		VALUES(?,'import',?,?,'dead',?,'unknown')`, name, now, home, now)
	return err
}

// ── 每群 swarm.db 的 members / cards ────────────────────────────────────

// importSwarmDetail 把成员与卡片搬进主库，好让它们能和 sessions join
// （成员会话死了还得找回它的日志）。**posts 一个字节都不碰**：
// 它是广场聊天流、全系统写得最频繁的表，并进主库只会让主库写锁竞争变差，
// 而且「删掉一个蜂群」现在是删一个目录，并进去就要变成一串带外键的 DELETE。
func importSwarmDetail(tx *sql.Tx, opt Options, rep *Report) error {
	// 蜂群库在 HomeDir 下（ROAM_DATA 可以把 DataDir 指到别处，两者不一定相同）。
	dirs, _ := filepath.Glob(filepath.Join(opt.HomeDir, "swarms", "*", "swarm.db"))
	known, err := knownSwarms(tx)
	if err != nil {
		return err
	}
	sort.Strings(dirs)
	for _, dbPath := range dirs {
		sid := filepath.Base(filepath.Dir(dbPath))
		if !known[sid] {
			// 孤儿目录：swarms 表里没有登记，直接搬会被 FK 挡下。
			rep.SkippedSwarms = append(rep.SkippedSwarms, sid)
			continue
		}
		if err := copySwarmDetail(tx, dbPath, sid, rep); err != nil {
			fmt.Fprintf(os.Stderr, "ttmux: 收编 %s 失败，跳过: %v\n", sid, err)
		}
	}
	return nil
}

func knownSwarms(tx *sql.Tx) (map[string]bool, error) {
	rows, err := tx.Query(`SELECT id FROM swarms`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var s string
		if rows.Scan(&s) == nil {
			out[s] = true
		}
	}
	return out, rows.Err()
}

func copySwarmDetail(tx *sql.Tx, dbPath, swarmID string, rep *Report) error {
	src, err := sql.Open("sqlite", "file:"+dbPath+"?_pragma=busy_timeout(5000)&mode=ro")
	if err != nil {
		return err
	}
	defer src.Close()

	// 老 swarm.db 的 members 可能缺列（kind/role/subrole/duty/session 都是后加的）。
	// 按实际列集合构造 SELECT，缺的用零值——写死列名会让整个群搬不过来。
	if HasTable(src, "members") {
		have, err := Columns(src, "members")
		if err != nil {
			return err
		}
		want := []string{"name", "type", "task", "workdir", "status", "deps", "done",
			"pending", "model", "perm", "kind", "role", "subrole", "duty", "session"}
		var sel []string
		var present []string
		for _, c := range want {
			if !have[c] {
				continue
			}
			present = append(present, c)
			if c == "done" || c == "pending" {
				sel = append(sel, "IFNULL("+c+",0)")
			} else {
				sel = append(sel, "IFNULL("+c+",'')")
			}
		}
		if len(present) > 0 {
			rows, err := src.Query(`SELECT ` + strings.Join(sel, ",") + ` FROM members`)
			if err != nil {
				return err
			}
			ph := strings.TrimSuffix(strings.Repeat("?,", len(present)+1), ",")
			ins := `INSERT OR IGNORE INTO swarm_members(swarm_id,` + strings.Join(present, ",") +
				`) VALUES(` + ph + `)`
			for rows.Next() {
				vals := make([]any, len(present))
				ptrs := make([]any, len(present))
				for i := range vals {
					ptrs[i] = &vals[i]
				}
				if rows.Scan(ptrs...) != nil {
					continue
				}
				res, err := tx.Exec(ins, append([]any{swarmID}, vals...)...)
				if err != nil {
					rows.Close()
					return err
				}
				if n, _ := res.RowsAffected(); n > 0 {
					rep.Members++
				}
			}
			rows.Close()
		}
	}

	if HasTable(src, "cards") {
		rows, err := src.Query(`SELECT id, IFNULL(title,''), IFNULL(descr,''), IFNULL(assignee,''),
			IFNULL(col,'backlog'), IFNULL(deps,''), IFNULL(created,''), IFNULL(updated,'') FROM cards`)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var cid, title, descr, assignee, col, deps, created, updated string
			if rows.Scan(&cid, &title, &descr, &assignee, &col, &deps, &created, &updated) != nil {
				continue
			}
			res, err := tx.Exec(`INSERT OR IGNORE INTO swarm_cards
				(swarm_id,id,title,descr,assignee,col,deps,created,updated)
				VALUES(?,?,?,?,?,?,?,?,?)`,
				swarmID, cid, title, descr, assignee, col, deps, created, updated)
			if err != nil {
				return err
			}
			if n, _ := res.RowsAffected(); n > 0 {
				rep.Cards++
			}
		}
	}
	return nil
}

// ── activity.log ────────────────────────────────────────────────────────

type legacyTrace struct {
	ID         string `json:"id"`
	Repo       string `json:"repo"`
	Branch     string `json:"branch"`
	HeadOid    string `json:"headOid"`
	Base       string `json:"base"`
	Action     string `json:"action"`
	Strategy   string `json:"strategy"`
	At         int64  `json:"at"`
	MergedInto string `json:"mergedInto"`
	MergedKind string `json:"mergedKind"`
}

// importTraces 收编 activity.log（两代）。
//
// 与别的收编不同，这份是 **JSONL 而非 JSON**：一行坏了只丢那一行，不该让整个文件
// 作废——留痕本来就是「尽力而为的摘要」，半条记录不值得挡住迁移。
func importTraces(tx *sql.Tx, opt Options) error {
	if opt.DataDir == "" {
		return errNoDataDir
	}
	n := 0
	// 先老（.1）后新：同 id 撞上时 INSERT OR IGNORE 保留先插进去的那条，
	// 而两代之间本来就不会有同 id，顺序只是让 rowid 与时间同向。
	for _, name := range []string{"activity.log.1", "activity.log"} {
		b, err := os.ReadFile(filepath.Join(opt.DataDir, name))
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return err
		}
		for _, line := range strings.Split(string(b), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var e legacyTrace
			if json.Unmarshal([]byte(line), &e) != nil {
				continue // 半条/坏行：丢它一条，别丢整个文件
			}
			if e.ID == "" {
				e.ID = traceID(line) // 老行没有 id 字段；按内容派一个，重跑不会翻倍
			}
			res, err := tx.Exec(`INSERT OR IGNORE INTO project_traces
				(id,repo,branch,head_oid,base,action,strategy,at,merged_into,merged_kind)
				VALUES(?,?,?,?,?,?,?,?,?,?)`,
				e.ID, e.Repo, e.Branch, e.HeadOid, e.Base, e.Action, e.Strategy, e.At,
				e.MergedInto, e.MergedKind)
			if err != nil {
				return err
			}
			if aff, _ := res.RowsAffected(); aff > 0 {
				n++
			}
		}
	}
	// 收编那步（v3）在老机器上早已盖过章，这里只补自己这一格。
	lastReport.Traces = n
	return nil
}

// traceID 给没有 id 的老留痕派一个稳定 id：同一行内容永远得到同一个 id，
// 于是「导一半崩了再来一遍」不会把已经进库的那些翻倍。
func traceID(line string) string {
	h := fnv.New64a()
	_, _ = h.Write([]byte(line))
	return fmt.Sprintf("t-%016x", h.Sum64())
}
