package swarm

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	_ "modernc.org/sqlite"

	"github.com/ybz21/Roami/internal/storage"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

type Options struct {
	HomeDir string
	DataDir string
	TmuxBin string
	Now     func() time.Time
}

type SwarmStatus struct {
	Name           string         `json:"name"`
	Goal           string         `json:"goal"`
	Status         string         `json:"status"`
	Supervisor     string         `json:"supervisor"`
	Created        string         `json:"created"`
	Dir            string         `json:"dir"` // 工作目录(绝对路径, 可空)：Web 按它把蜂群归到项目
	LeaderLastPost int64          `json:"leader_last_post"`
	Members        []SwarmMember  `json:"members"`
	Pending        []SwarmPending `json:"pending"`
	DoneMarked     []string       `json:"done_marked"`
}

type SwarmMember struct {
	Name    string `json:"name"`
	Type    string `json:"type"`
	Task    string `json:"task"`
	Deps    string `json:"deps"`
	Done    int    `json:"done"`
	Kind    string `json:"kind"`
	Role    string `json:"role"`
	Subrole string `json:"subrole"`
	Duty    string `json:"duty"`
	Status  string `json:"status"`
	// Session 会话名(= 会话 id)：打开终端/发消息的 handle。
	// Label 会话展示名 `<群>-<成员>`：给人看的，也是老用法 `roami session send <群>-<成员>` 的入口。
	Session string `json:"session"`
	Label   string `json:"label,omitempty"`
}

type SwarmPending struct {
	Name string `json:"name"`
	Deps string `json:"deps"`
}

type swarmMeta struct {
	ID         string
	Name       string
	Goal       string
	Status     string
	Supervisor string
	Created    string
	Dir        string
}

func DefaultOptions() Options {
	home, _ := os.UserHomeDir()
	homeDir := firstEnv("ROAMI_HOME", "ROAM_HOME", "TTMUX_HOME")
	if homeDir == "" {
		homeDir = filepath.Join(home, ".roami")
	}
	dataDir := firstEnv("ROAMI_DATA", "ROAM_DATA", "TTMUX_DATA")
	if dataDir == "" {
		dataDir = homeDir
	}
	tmux := os.Getenv("TMUX_BIN")
	if tmux == "" {
		var err error
		tmux, err = exec.LookPath("tmux")
		if err != nil {
			tmux = "tmux"
		}
	}
	return Options{
		HomeDir: homeDir,
		DataDir: dataDir,
		TmuxBin: tmux,
		Now:     time.Now,
	}
}

// firstEnv 返回首个非空环境变量值（ROAMI_* 主键，兼容旧 ROAM_* / TTMUX_*）。
func firstEnv(keys ...string) string {
	for _, k := range keys {
		if v := os.Getenv(k); v != "" {
			return v
		}
	}
	return ""
}

func (o Options) withDefaults() Options {
	d := DefaultOptions()
	if o.HomeDir == "" {
		o.HomeDir = d.HomeDir
	}
	if o.DataDir == "" {
		o.DataDir = d.DataDir
	}
	if o.TmuxBin == "" {
		o.TmuxBin = d.TmuxBin
	}
	if o.Now == nil {
		o.Now = d.Now
	}
	return o
}

// SessionNames returns the set of tmux session names that belong to swarms
// (swarm supervisors plus all group members), mirroring bash _is_swarm_session.
// Failures degrade silently to a smaller set, matching the shell behaviour of
// hiding swarm sessions only when the metadata is reachable.
func SessionNames(opt Options) map[string]bool {
	opt = opt.withDefaults()
	set := map[string]bool{}
	names := map[string]bool{}

	metaPath := metaPathFor(opt.HomeDir, opt.DataDir)
	if _, err := os.Stat(metaPath); err == nil {
		if db, err := openMeta(opt.HomeDir, opt.DataDir); err == nil {
			if rows, err := db.Query(`SELECT name, IFNULL(supervisor,'') FROM swarms`); err == nil {
				for rows.Next() {
					var name, sup string
					if rows.Scan(&name, &sup) == nil {
						if name != "" {
							names[name] = true
						}
						if sup != "" {
							set[sup] = true
						}
					}
				}
				rows.Close()
			}
			db.Close()
		}
	}

	// Legacy layout: directories under DataDir/swarms also count as swarm names.
	if entries, err := os.ReadDir(filepath.Join(opt.DataDir, "swarms")); err == nil {
		for _, e := range entries {
			if e.IsDir() {
				names[e.Name()] = true
			}
		}
	}

	for name := range names {
		b, err := os.ReadFile(filepath.Join(opt.DataDir, "groups", name+".group"))
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(b), "\n") {
			if line = strings.TrimSpace(line); line != "" {
				set[line] = true
			}
		}
	}
	return set
}

// Names returns the set of swarm names (meta.db registry plus legacy dirs
// under DataDir/swarms), mirroring _swarm_names. Used to hide swarm groups
// from the plain group listing.
func Names(opt Options) map[string]bool {
	opt = opt.withDefaults()
	names := map[string]bool{}
	metaPath := metaPathFor(opt.HomeDir, opt.DataDir)
	if _, err := os.Stat(metaPath); err == nil {
		if db, err := openMeta(opt.HomeDir, opt.DataDir); err == nil {
			if rows, err := db.Query(`SELECT name FROM swarms`); err == nil {
				for rows.Next() {
					var n string
					if rows.Scan(&n) == nil && n != "" {
						names[n] = true
					}
				}
				rows.Close()
			}
			db.Close()
		}
	}
	if entries, err := os.ReadDir(filepath.Join(opt.DataDir, "swarms")); err == nil {
		for _, e := range entries {
			if e.IsDir() {
				names[e.Name()] = true
			}
		}
	}
	return names
}

func StatusJSON(name string, opt Options) ([]byte, error) {
	st, err := Status(name, opt)
	if err != nil {
		return nil, err
	}
	return json.Marshal(st)
}

func Status(name string, opt Options) (*SwarmStatus, error) {
	opt = opt.withDefaults()
	metaDB, err := openMeta(opt.HomeDir, opt.DataDir)
	if err != nil {
		return nil, err
	}
	defer metaDB.Close()
	meta, err := findSwarm(metaDB, name)
	if err != nil {
		return nil, err
	}
	db := metaDB // members 已并进主库，按 swarm_id 分群

	status := &SwarmStatus{
		Name:           meta.Name,
		Goal:           meta.Goal,
		Status:         meta.Status,
		Supervisor:     meta.Supervisor,
		Created:        meta.Created,
		Dir:            meta.Dir,
		LeaderLastPost: readLeaderLastPost(opt.HomeDir, meta.ID),
		Members:        []SwarmMember{},
		Pending:        []SwarmPending{},
		DoneMarked:     []string{},
	}

	rows, err := db.Query(`SELECT name, IFNULL(type,'agent'), IFNULL(task,''), IFNULL(deps,''), IFNULL(done,0), IFNULL(kind,'claude'),
		CASE IFNULL(role,'member') WHEN 'master' THEN 'leader' WHEN 'worker' THEN 'member' ELSE IFNULL(role,'member') END,
		IFNULL(subrole,''), IFNULL(duty,''), IFNULL(session,'')
		FROM swarm_members WHERE swarm_id=? AND IFNULL(pending,0)=0 ORDER BY name`, meta.ID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var m SwarmMember
		if err := rows.Scan(&m.Name, &m.Type, &m.Task, &m.Deps, &m.Done, &m.Kind, &m.Role, &m.Subrole, &m.Duty, &m.Session); err != nil {
			return nil, err
		}
		// Session 是会话名(= 会话 id)；Label 是展示名 `<群>-<成员>`。没落过 session
		// 的（迁移前建的成员）按展示名现查一次，查不到就退回展示名本身。
		m.Label = MemberLabel(meta.Name, m.Name)
		if m.Session == "" {
			m.Session = runtime.Runtime{TmuxBin: opt.TmuxBin}.ResolveAlive(m.Label)
		}
		if m.Done == 1 {
			m.Status = "done"
		} else {
			m.Status = liveStatus(opt, meta, m)
		}
		status.Members = append(status.Members, m)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	prows, err := db.Query(`SELECT name, IFNULL(deps,'') FROM swarm_members WHERE swarm_id=? AND IFNULL(pending,0)=1 ORDER BY name`, meta.ID)
	if err != nil {
		return nil, err
	}
	defer prows.Close()
	for prows.Next() {
		var p SwarmPending
		if err := prows.Scan(&p.Name, &p.Deps); err != nil {
			return nil, err
		}
		status.Pending = append(status.Pending, p)
	}
	if err := prows.Err(); err != nil {
		return nil, err
	}

	drows, err := db.Query(`SELECT name FROM swarm_members WHERE swarm_id=? AND IFNULL(done,0)=1 ORDER BY name`, meta.ID)
	if err != nil {
		return nil, err
	}
	defer drows.Close()
	for drows.Next() {
		var name string
		if err := drows.Scan(&name); err != nil {
			return nil, err
		}
		status.DoneMarked = append(status.DoneMarked, name)
	}
	return status, drows.Err()
}

// sharedDB 是 metadb 共享连接的一层皮：Close 空转。
//
// 本包有几十处 `db, err := open...(); defer db.Close()` 的写法。连接层换成进程级
// 共享池之后，那些 Close 一旦真关，就会把长驻 plugind 和其它包正在用的同一个库关掉。
// 与其改动几十个调用点，不如让 Close 变成空操作——库的生命周期本就该由 metadb 管，
// 不该由某一次读写决定。
type sharedDB struct{ *metadb.DB }

func (sharedDB) Close() error { return nil }

// openMeta 打开主库（meta.db）。schema 与迁移都在 internal/metadb 的版本链里。
func openMeta(homeDir, dataDir string) (sharedDB, error) {
	d, err := metadb.Open(homeDir, metadb.Options{DataDir: dataDir, HomeDir: homeDir})
	return sharedDB{d}, err
}

// openSwarmFile 打开某个蜂群自己的库。它只装 posts（广场聊天流）——
// members/cards 已经并进主库，好和 sessions join。
func openSwarmFile(path string) (sharedDB, error) {
	d, err := metadb.OpenFile(path, swarmSteps, metadb.Options{})
	return sharedDB{d}, err
}

// swarmSteps 是每群那个库的版本链。posts 留在这里不并主库：它是全系统写得最频繁的
// 表，并进去只会让主库写锁竞争变差；而且「删掉一个蜂群」现在是删一个目录，
// 并进去就要变成一串带外键的 DELETE。
var swarmSteps = []metadb.Step{
	{Version: 1, Name: "swarm-db", SQL: `
		CREATE TABLE IF NOT EXISTS members(
			name TEXT PRIMARY KEY, type TEXT, task TEXT, workdir TEXT,
			status TEXT, deps TEXT, done INT DEFAULT 0, pending INT DEFAULT 0,
			model TEXT, perm TEXT,
			kind TEXT DEFAULT 'claude', role TEXT DEFAULT 'member',
			subrole TEXT DEFAULT '', duty TEXT DEFAULT '',
			session TEXT DEFAULT '');
		CREATE TABLE IF NOT EXISTS posts(
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			ts TEXT, author TEXT, kind TEXT, re INTEGER, text TEXT);
		CREATE TABLE IF NOT EXISTS cards(
			id TEXT PRIMARY KEY, title TEXT, descr TEXT, assignee TEXT,
			col TEXT DEFAULT 'backlog', deps TEXT, created TEXT, updated TEXT);`,
		Fn: adoptSwarmMemberColumns},
}

// adoptSwarmMemberColumns 给老的 members 表补列，并把 legacy 的 master/worker 角色归一。
// 原先这段是每次开库都跑一遍的 migrateSwarmDB；现在只在版本链上跑一次。
func adoptSwarmMemberColumns(tx *sql.Tx, _ metadb.Options) error {
	cols, err := metadb.Columns(tx, "members")
	if err != nil {
		return err
	}
	add := map[string]string{
		"kind": "TEXT DEFAULT 'claude'", "role": "TEXT DEFAULT 'member'",
		"subrole": "TEXT DEFAULT ''", "duty": "TEXT DEFAULT ''",
		// session：成员的 tmux 会话名(= 会话 id)。会话名不再能从 `<群>-<成员>` 推导
		// （那只是展示名），而会话死后展示名也随之消失——必须落一列，否则「会话没了
		// 但有日志 = 已完成」这类判定会找不到日志文件（日志按 id 命名）。
		"session": "TEXT DEFAULT ''",
	}
	for _, n := range []string{"kind", "role", "subrole", "duty", "session"} {
		if cols[n] {
			continue
		}
		if _, err := tx.Exec(`ALTER TABLE members ADD COLUMN ` + n + ` ` + add[n]); err != nil {
			return err
		}
	}
	if _, err := tx.Exec(`UPDATE members SET role='leader' WHERE role='master'`); err != nil {
		return err
	}
	_, err = tx.Exec(`UPDATE members SET role='member' WHERE role='worker' OR IFNULL(role,'')=''`)
	return err
}

func findSwarm(db sharedDB, name string) (swarmMeta, error) {
	var m swarmMeta
	err := db.QueryRow(`SELECT id, name, IFNULL(goal,''), IFNULL(status,''), IFNULL(supervisor,''), IFNULL(created,''), IFNULL(dir,'')
		FROM swarms WHERE name=? OR id=? LIMIT 1`, name, name).
		Scan(&m.ID, &m.Name, &m.Goal, &m.Status, &m.Supervisor, &m.Created, &m.Dir)
	if errors.Is(err, sql.ErrNoRows) {
		return m, fmt.Errorf("swarm not found: %s", name)
	}
	return m, err
}

func readLeaderLastPost(home, id string) int64 {
	b, err := os.ReadFile(filepath.Join(home, "swarms", id, "listeners", "leader.last_post"))
	if err != nil {
		return 0
	}
	var n int64
	_, _ = fmt.Sscanf(strings.TrimSpace(string(b)), "%d", &n)
	return n
}

func liveStatus(opt Options, meta swarmMeta, m SwarmMember) string {
	if !tmuxHasSession(opt.TmuxBin, m.Session) {
		if _, err := os.Stat(filepath.Join(opt.DataDir, "logs", m.Session+".log")); err == nil {
			return "done"
		}
		return "exited"
	}
	dead := strings.TrimSpace(runTmux(opt.TmuxBin, "display-message", "-t", "="+m.Session+":", "-p", "#{pane_dead}"))
	if dead == "1" {
		return "done"
	}
	recent := captureRecent(opt.TmuxBin, m.Session)
	flat := strings.ToLower(removeSpace(recent))
	if strings.Contains(flat, "pressenter") || strings.Contains(flat, "pressente") || strings.Contains(flat, "1.yes") ||
		strings.Contains(flat, "doyouwant") || strings.Contains(flat, "allow") || strings.Contains(flat, "approval") {
		return "waiting"
	}
	if strings.Contains(recent, "Cooking") || strings.Contains(recent, "Puzzling") || strings.Contains(recent, "Thinking") ||
		strings.Contains(recent, "Working") || strings.Contains(recent, "Running") || strings.Contains(recent, "Executing") {
		return "running"
	}
	if strings.Contains(recent, "✻") && !strings.Contains(recent, "Worked for") {
		return "running"
	}
	if !strings.Contains(recent, "Worked for") && busyRecent(opt, meta, m) {
		return "running"
	}
	if strings.Contains(recent, "❯") || strings.Contains(recent, "›") || strings.Contains(recent, "⏵⏵") || strings.TrimSpace(recent) == ">" {
		return "idle"
	}
	if m.Kind == "codex" {
		return "idle"
	}
	return "running"
}

func tmuxHasSession(bin, session string) bool {
	// "=" 强制精确匹配:tmux -t 默认按前缀匹配,dev 会话死后 has-session
	// 会命中它的陪跑会话 <dev>-review,导致存活误判、退出/完成事件永不触发。
	cmd := exec.Command(bin, "has-session", "-t", "="+session)
	return cmd.Run() == nil
}

func runTmux(bin string, args ...string) string {
	var out bytes.Buffer
	cmd := exec.Command(bin, args...)
	cmd.Stdout = &out
	_ = cmd.Run()
	return out.String()
}

func captureRecent(bin, session string) string {
	out := runTmux(bin, "capture-pane", "-t", "="+session, "-p", "-J", "-S", "-80")
	lines := strings.Split(out, "\n")
	if len(lines) > 18 {
		lines = lines[len(lines)-18:]
	}
	if len(lines) > 8 {
		lines = lines[len(lines)-8:]
	}
	return strings.Join(lines, "\n")
}

func removeSpace(s string) string {
	return strings.Join(strings.Fields(s), "")
}

func busyRecent(opt Options, meta swarmMeta, m SwarmMember) bool {
	b, err := os.ReadFile(filepath.Join(opt.HomeDir, "swarms", meta.ID, "busy", m.Name+".busy"))
	if err != nil {
		return false
	}
	var ts int64
	if _, err := fmt.Sscanf(strings.TrimSpace(string(b)), "%d", &ts); err != nil {
		return false
	}
	ttl := int64(45)
	if v := strings.TrimSpace(os.Getenv("TTMUX_SWARM_BUSY_TTL")); v != "" {
		var n int64
		if _, err := fmt.Sscanf(v, "%d", &n); err == nil && n > 0 {
			ttl = n
		}
	}
	return opt.Now().Unix()-ts <= ttl
}

func metaPathFor(home, data string) string {
	p, _ := metadb.ResolvePaths(home, data)
	return p.MainPath()
}
