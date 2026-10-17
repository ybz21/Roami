package metadb

import (
	"database/sql"
	"fmt"
	"sort"
	"strings"
	"time"
)

// mainSteps 是 meta.db 的版本链。
//
// **只增不改**：新列一律 nullable 或带默认值，不改名、不删列、不改类型
// （理由见 migrate.go 末尾）。新增演进就往后面追加一个 Step，永远不要改动已发布的那些。
var mainSteps = []Step{
	{Version: 1, Name: "baseline", Fn: baseline},
	{Version: 2, Name: "ledger-tables", SQL: ledgerTables},
	{Version: 3, Name: "import-legacy", Fn: importLegacy},
	{Version: 4, Name: "agent-session", Fn: addAgentSession},
	{Version: 5, Name: "project-traces", SQL: createProjectTraces},
	{Version: 6, Name: "import-traces", Fn: importTraces},
	{Version: 7, Name: "lazy-revive", Fn: addLazyRevive},
	{Version: 8, Name: "session-memory", Fn: addSessionMemory},
	{Version: 9, Name: "session-oom", Fn: addSessionOOM},
	{Version: 10, Name: "session-mem-alert", Fn: addSessionMemAlert},
}

// addSessionMemAlert 记「已经就这个会话的内存提醒过什么」，用来只提醒一次。
//
// 两列而不是一列：一个会话可能先在 85% 档被提醒过，后来又真的撞顶被杀——
// 那是两件事，各自都该说一次。挤进一列就得编码，编码就会有人看不懂。
//
//   - mem_alert_level：已提醒过的档位（0 = 没提醒过 / 85 = 提醒过 85% 档）。
//     跌回阈值以下会清零，于是再涨上去会重新提醒——这是想要的：它又涨回来了。
//   - mem_alert_ooms：已就「撞顶被杀」提醒到第几次。cgroup 的 oom_kill 是累计值，
//     记下已通知到哪一次，新增的才提醒。
func addSessionMemAlert(tx *sql.Tx, _ Options) error {
	return addColumns(tx, "sessions", map[string]string{
		"mem_alert_level": "INTEGER",
		"mem_alert_ooms":  "INTEGER",
	})
}

// addSessionOOM 给 sessions 加 oom_kills：这个会话撞过几次自己的内存上限。
//
// 和 peak_rss 一样必须**趁会话活着时**落库。一开始想的是「发现它没了的时候
// 读一眼 memory.events」——读不到：cgroup 目录随最后一个进程退出就消失，
// 那时已经没地方问了（实测把会话压到撞顶，scope 目录当场没，只能记成 killed）。
//
// 单独开一个 step 而不是塞进 step 8：step 8 已经在本机跑过，schema_meta 记着 8
// 就不会重跑，往里加列等于白加——今天刚在 restored_from 上栽过一次
// （见 addLazyRevive 的注释），这里立刻又差点重演。
func addSessionOOM(tx *sql.Tx, _ Options) error {
	return addColumns(tx, "sessions", map[string]string{"oom_kills": "INTEGER"})
}

// addSessionMemory 给 sessions 加 peak_rss：这个会话峰值吃了多少内存。
//
// 会话没了之后 cgroup 目录跟着消失，那时再想知道「它涨到过多少」已经晚了——
// 2026-08-22 那次得靠翻内核 OOM dump 才查出是哪个进程。所以在它还活着的时候
// 就把 memory.peak 抄进台账，配合 died_reason='oom' 就能直接回答
// 「机器怎么又卡了」：哪个会话、涨到多少、是不是撞了上限。
func addSessionMemory(tx *sql.Tx, _ Options) error {
	return addColumns(tx, "sessions", map[string]string{
		"peak_rss": "INTEGER",
	})
}

// addLazyRevive 补齐「会话懒恢复」要用的三列，顺带修一个静默了很久的洞。
//
// restored_from 本该由 step 4 建出来，但它是**后来**被加进那个已发布步骤的：
// 库跑过 step 4 之后 schema_meta 就记了 4，再改 addAgentSession 也不会重跑。
// 于是所有 2026-08-12 之后升级的库都没有这一列，SetRestoredFrom 一直在
// 静默失败（调用方 `_ =` 吞了错）。addColumns 是幂等的，这里无条件补一次。
// —— 这正是文件开头那句「只增不改，永远不要改动已发布的那些」防的事。
func addLazyRevive(tx *sql.Tx, _ Options) error {
	return addColumns(tx, "sessions", map[string]string{
		"restored_from": "TEXT",
		// agent_kind 决定恢复时敲哪个命令。没有它就只能硬编码 claude，
		// 于是 codex 会话会被敲成 `claude --resume <codex的对话id>`。
		"agent_kind": "TEXT",
		// last_seen 让 host-restart 的 died_at 能取「最后一次看见它」而不是
		// 「开机后第一次 Reconcile」——后者差了整整一夜。
		"last_seen": "TEXT",
	})
}

// createProjectTraces 收尾留痕（合入 / 丢弃 / 清理）进表。
//
// 它原先是 <dataDir>/activity.log —— 一个只追加的 JSONL，5MB 轮转一代。那形态在
// M2 并库时被漏下了，代价是双重的：一来重启后它跟别的台账不在同一份快照里，
// 备份/恢复各走各的；二来 M2 之后 Store 在直连模式下压根不再有文件路径，
// 于是每一条留痕都被静默丢弃、项目活动恒空（这个洞由本步骤连带堵上）。
//
// 建表与收编分成两步：DataDir 拿不到时收编那步会推迟（plugind 之类的入口开库
// 时就没有），但表必须先建出来 —— 否则后端接上库却无处可写。
const createProjectTraces = `
CREATE TABLE IF NOT EXISTS project_traces(
	id          TEXT PRIMARY KEY,
	repo        TEXT NOT NULL DEFAULT '',
	branch      TEXT,
	head_oid    TEXT,
	base        TEXT,
	action      TEXT,
	strategy    TEXT,
	at          INTEGER NOT NULL DEFAULT 0,
	merged_into TEXT,
	merged_kind TEXT
);
CREATE INDEX IF NOT EXISTS project_traces_repo ON project_traces(repo, at DESC);
`

// addAgentSession 给 sessions 加 agent_session_uuid：agent 那一侧的对话 id。
//
// Claude Code 的对话存在 ~/.claude/projects/<cwd-slug>/<uuid>.jsonl，与 tmux 无关，
// 重启一段不丢——缺的只是「哪份 transcript 属于哪个会话」。靠 cwd + 取最新文件猜
// 只在会话活着时勉强成立，会话一死就失准（同目录的别的会话会赢）。
// 所以改成由我们**指定**：拉起 agent 时传 --session-id，关联由构造保证。
func addAgentSession(tx *sql.Tx, _ Options) error {
	// restored_from 是软引用（只存 id、不加 FK）：被重开的那一行可能已经过了
	// 保留期被清掉，而「这个会话是重开出来的」这个事实本身仍然成立。
	return addColumns(tx, "sessions", map[string]string{
		"agent_session_uuid": "TEXT",
		"restored_from":      "TEXT",
	})
}

// ── step 1 ──────────────────────────────────────────────────────────────
//
// 野外的库有各种组合：sessions 可能是 v1/v2/v3，swarms 可能没有 dir 列，
// plugins 可能没有 install_path/removed，plugin 那四张表可能一张都没有。
// 逐一辨识是徒劳的，所以 baseline 定义成一个**幂等收敛器**：
// 任何老库跑完它，都等于今天所有代码开库之后的那个状态；从这一刻起再也不推断，
// 一切靠 schema_meta。全新空库跑同一段代码得到同一个结果，不需要分支。

const createSessionsV3 = `CREATE TABLE IF NOT EXISTS sessions(
	id TEXT PRIMARY KEY,
	parent_id TEXT,
	created_by TEXT,
	created_at TEXT,
	initial_cwd TEXT,
	status TEXT NOT NULL DEFAULT 'live',
	died_at TEXT,
	died_reason TEXT,
	tmux_id TEXT,
	tmux_epoch TEXT
)`

const createSwarms = `CREATE TABLE IF NOT EXISTS swarms(
	id TEXT PRIMARY KEY, name TEXT UNIQUE, goal TEXT,
	status TEXT, supervisor TEXT, created TEXT, dir TEXT)`

var createPluginTables = []string{
	`CREATE TABLE IF NOT EXISTS plugins (
		id TEXT PRIMARY KEY, version TEXT, kind TEXT,
		enabled INTEGER DEFAULT 0, manifest TEXT, installed TEXT,
		install_path TEXT, removed INTEGER DEFAULT 0)`,
	`CREATE TABLE IF NOT EXISTS plugin_sessions (
		session TEXT PRIMARY KEY, plugin TEXT, job TEXT, labels TEXT,
		status TEXT DEFAULT 'running', created TEXT, updated TEXT)`,
	`CREATE TABLE IF NOT EXISTS plugin_findings (
		id INTEGER PRIMARY KEY AUTOINCREMENT, plugin TEXT, job TEXT,
		severity TEXT, title TEXT, file TEXT, line INTEGER,
		detail TEXT, status TEXT DEFAULT 'open', created TEXT, updated TEXT)`,
	`CREATE TABLE IF NOT EXISTS plugin_notifications (
		id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, severity TEXT,
		title TEXT, body TEXT, source TEXT, dedupe TEXT, created TEXT)`,
}

func baseline(tx *sql.Tx, opt Options) error {
	if err := adoptSessions(tx, opt); err != nil {
		return err
	}
	if _, err := tx.Exec(createSwarms); err != nil {
		return err
	}
	if err := addColumns(tx, "swarms", map[string]string{"dir": "TEXT"}); err != nil {
		return err
	}
	for _, q := range createPluginTables {
		if _, err := tx.Exec(q); err != nil {
			return err
		}
	}
	return addColumns(tx, "plugins", map[string]string{
		"install_path": "TEXT",
		"removed":      "INTEGER DEFAULT 0",
	})
}

// addColumns 按需补列。原先各包是「裸 ALTER + 吞 duplicate column 错误」，
// 那样连真错误也一起吞了；先读列集合再决定，错误就能如实往上抛。
func addColumns(tx *sql.Tx, table string, cols map[string]string) error {
	have, err := Columns(tx, table)
	if err != nil {
		return err
	}
	names := make([]string, 0, len(cols))
	for n := range cols {
		names = append(names, n)
	}
	sort.Strings(names) // 定序：同一个库在不同机器上补列顺序一致
	for _, n := range names {
		if have[n] {
			continue
		}
		if _, err := tx.Exec(fmt.Sprintf(`ALTER TABLE %s ADD COLUMN %s %s`, table, n, cols[n])); err != nil {
			return err
		}
	}
	return nil
}

// adoptSessions 把 v1（会话名当主键，列 session）/ v2（$N 当主键，列 name）搬成 v3。
// 逻辑与原 sessmeta.ensureSchema 逐字等价，只是搬进来并去掉它自己那次 io.Copy 备份
// （备份改由 DB.prepare 统一用 VACUUM INTO 做）。
//
// 两代迁移都**不依赖 tmux**：v1 的主键就是现在要的持久会话 id；v2 用同表内的
// id→name 映射翻译 parent。老实现要先问 tmux 要「名字 → $N」才肯搬，tmux 一死
// 就整批丢弃——那正是重启后会话历史被清空的第二重原因。
func adoptSessions(tx *sql.Tx, opt Options) error {
	if !HasTable(tx, "sessions") {
		_, err := tx.Exec(createSessionsV3)
		return err
	}
	cols, err := Columns(tx, "sessions")
	if err != nil {
		return err
	}
	if cols["status"] { // 已是 v3
		return nil
	}
	old := "sessions_v2"
	if cols["session"] {
		old = "sessions_v1"
	}
	if _, err := tx.Exec(`ALTER TABLE sessions RENAME TO ` + old); err != nil {
		return err
	}
	if _, err := tx.Exec(createSessionsV3); err != nil {
		return err
	}
	if old == "sessions_v1" {
		err = importSessionsV1(tx, opt)
	} else {
		err = importSessionsV2(tx, opt)
	}
	if err != nil {
		return err
	}
	_, err = tx.Exec(`DROP TABLE ` + old)
	return err
}

type legacySession struct {
	id, parent, createdBy, createdAt, cwd string
}

func importSessionsV1(tx *sql.Tx, opt Options) error {
	rows, err := tx.Query(`SELECT session, IFNULL(parent,''), IFNULL(created_by,''),
		IFNULL(created_at,''), IFNULL(initial_cwd,'') FROM sessions_v1`)
	if err != nil {
		return err
	}
	var all []legacySession
	for rows.Next() {
		var r legacySession
		if rows.Scan(&r.id, &r.parent, &r.createdBy, &r.createdAt, &r.cwd) == nil {
			all = append(all, r)
		}
	}
	rows.Close()
	return insertAdopted(tx, all, opt)
}

func importSessionsV2(tx *sql.Tx, opt Options) error {
	rows, err := tx.Query(`SELECT id, IFNULL(name,''), IFNULL(parent_id,''), IFNULL(created_by,''),
		IFNULL(created_at,''), IFNULL(initial_cwd,'') FROM sessions_v2`)
	if err != nil {
		return err
	}
	type v2row struct {
		tmuxID, parentTmuxID string
		r                    legacySession
	}
	var all []v2row
	name := map[string]string{}
	for rows.Next() {
		var x v2row
		if rows.Scan(&x.tmuxID, &x.r.id, &x.parentTmuxID, &x.r.createdBy,
			&x.r.createdAt, &x.r.cwd) == nil {
			all = append(all, x)
			name[x.tmuxID] = x.r.id
		}
	}
	rows.Close()
	out := make([]legacySession, 0, len(all))
	for _, x := range all {
		x.r.parent = name[x.parentTmuxID]
		out = append(out, x.r)
	}
	return insertAdopted(tx, out, opt)
}

// insertAdopted 落迁移来的行。一律先当 live —— 迁移器不问 tmux，
// 「看不见不等于死了」，判错也无妨：Reconcile 双向自愈。
func insertAdopted(tx *sql.Tx, rows []legacySession, opt Options) error {
	for _, r := range rows {
		if r.id == "" {
			continue
		}
		if _, err := tx.Exec(`INSERT OR IGNORE INTO sessions
			(id,parent_id,created_by,created_at,initial_cwd,status)
			VALUES(?,NULLIF(?,''),?,?,?,'live')`,
			r.id, r.parent, r.createdBy, r.createdAt, r.cwd); err != nil {
			return err
		}
	}
	return nil
}

// ── step 2 ──────────────────────────────────────────────────────────────
//
// 外键**只在同一个写者的表族内**声明。跨写者的引用一律软引用（只存 id、不加 FK）：
//   - sessions.parent_id：父会话经常没有自己的行（只有 fork 出来的孩子才写行），
//     加 FK 会直接打死 sessmeta 的 TestParentWithoutOwnRowKeepsTree 那条不变量。
//   - swarm_members.session：成员会话可能先于台账存在。
//   - races.dir / sessions.repo_root：指向 projects.dir，但那是后端写的表。
//
// 时间列统一 RFC3339 TEXT（sessions 已经是），一个库里两套时间格式是长期税。
// 存量的 swarms.created 是 'YYYY-MM-DD HH:MM:SS'，原样不动，登记为债。
const ledgerTables = `
CREATE TABLE IF NOT EXISTS tmux_epochs(
	epoch      TEXT PRIMARY KEY,
	started_at TEXT NOT NULL DEFAULT '',
	seen_at    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS projects(
	id              TEXT PRIMARY KEY,
	dir             TEXT NOT NULL UNIQUE,
	origin          TEXT NOT NULL DEFAULT '',
	display_name    TEXT,
	pinned          INTEGER NOT NULL DEFAULT 0,
	default_agent   TEXT,
	default_base    TEXT,
	first_seen      INTEGER NOT NULL DEFAULT 0,
	last_seen       INTEGER NOT NULL DEFAULT 0,
	last_session_at INTEGER NOT NULL DEFAULT 0,
	archived_at     INTEGER
);

CREATE TABLE IF NOT EXISTS project_aliases(
	alias      TEXT PRIMARY KEY,
	project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS races(
	id TEXT PRIMARY KEY, legacy_id TEXT, name TEXT,
	dir TEXT NOT NULL DEFAULT '', base TEXT, prompt TEXT,
	created_at TEXT, status TEXT NOT NULL DEFAULT 'running',
	winner TEXT, crown_done TEXT, contestants TEXT
);
CREATE INDEX IF NOT EXISTS races_dir ON races(dir, status);

CREATE TABLE IF NOT EXISTS session_homes(
	tmux_id   TEXT PRIMARY KEY,
	epoch     TEXT,
	name      TEXT,
	home      TEXT NOT NULL,
	pinned_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS swarm_members(
	swarm_id TEXT NOT NULL REFERENCES swarms(id) ON DELETE CASCADE,
	name TEXT NOT NULL,
	type TEXT, task TEXT, workdir TEXT, status TEXT, deps TEXT,
	done INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0,
	model TEXT, perm TEXT,
	kind TEXT NOT NULL DEFAULT 'claude', role TEXT NOT NULL DEFAULT 'member',
	subrole TEXT NOT NULL DEFAULT '', duty TEXT NOT NULL DEFAULT '',
	session TEXT NOT NULL DEFAULT '',
	PRIMARY KEY(swarm_id, name)
);
CREATE INDEX IF NOT EXISTS swarm_members_session ON swarm_members(session);

CREATE TABLE IF NOT EXISTS swarm_cards(
	swarm_id TEXT NOT NULL REFERENCES swarms(id) ON DELETE CASCADE,
	id TEXT NOT NULL, title TEXT, descr TEXT, assignee TEXT,
	col TEXT NOT NULL DEFAULT 'backlog', deps TEXT, created TEXT, updated TEXT,
	PRIMARY KEY(swarm_id, id)
);

CREATE INDEX IF NOT EXISTS sessions_status ON sessions(status, died_at);
`

// sessionLedgerColumns 是 step 2 给 sessions 补的列。
//
//   - home_dir：归属目录的**台账事实**（键是持久会话 id，会话死了也要留）。
//     与后端那张 session_homes 表分工：那张的键是 tmux $N，pane 一死就收敛，是运行时绑定。
//   - repo_root：建会话时算好的仓库根。不只是为了能 join —— worktree 事后会被删掉，
//     那时再从 home_dir 反推就永远推不出来了。台账该在事实还可知的时候记下来。
//   - label：展示名快照（会话一死 tmux 的 @roam_name 就没了）。
var sessionLedgerColumns = map[string]string{
	"home_dir":  "TEXT",
	"repo_root": "TEXT",
	"label":     "TEXT",
}

func init() {
	// step 2 的 ALTER 部分要读列集合，只能走 Fn；DDL 部分走 SQL。
	for i := range mainSteps {
		if mainSteps[i].Version == 2 {
			mainSteps[i].Fn = func(tx *sql.Tx, _ Options) error {
				if err := addColumns(tx, "sessions", sessionLedgerColumns); err != nil {
					return err
				}
				_, err := tx.Exec(`CREATE INDEX IF NOT EXISTS sessions_home ON sessions(home_dir, status)`)
				return err
			}
		}
	}
}

// rfc3339 是本包统一的时间写法。
func rfc3339(t time.Time) string { return t.Format(time.RFC3339) }

// sqlList 把字符串切片拼成 IN (...) 的参数占位与实参。
func sqlList(items []string) (string, []any) {
	if len(items) == 0 {
		return "", nil
	}
	args := make([]any, len(items))
	for i, s := range items {
		args[i] = s
	}
	return strings.TrimSuffix(strings.Repeat("?,", len(items)), ","), args
}
