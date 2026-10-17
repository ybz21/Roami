// Package sessmeta 是通用 SessionMeta 数据层：meta.db 的 sessions 表。
// 只存「创建关系」等通用信息（parent/created_by/created_at/initial_cwd），
// 不存 worktree 字段——session↔worktree 归属由上层现算（设计 07 §2.1/§2.4）。
// parent 即 subSession 的 PPID：tmux 会话表保持平坦，树是本表的投影。
//
// 主键是**持久会话 id**（= tmux 会话名，见 docs/design/session-identity.md）：
// 它由创建时刻派生、不可变、跨 tmux server 重启唯一且永不复用。
// 曾经用 tmux 自己的 `#{session_id}`（`$3`）当主键，那是错的：`$N` 随 server 生死，
// 机器一重启就全部消失、并从 `$0` 重新发号，于是 Reconcile 把整张表判成死行清空
// （历史会话一条不剩），新会话还会撞上旧 `$N` 继承死会话的父子关系。`$N` 现在
// 降级成一列运行时句柄 `tmux_id`，只用来对活会话做一次身份确认。
//
// **会话死了不删行，只置 `status='dead'`。** 会话历史（在哪个目录、谁建的、日志
// 在哪）是用户数据，不是 tmux 的派生物；tmux 只回答「现在谁活着」。行数由 Prune
// 按保留条数收口。
//
// 老库自动迁移，两代都不丢数据：
//   - v1（会话名当主键，列 `session`）→ 主键正好就是现在要的持久 id，直接搬；
//   - v2（`$N` 当主键，列 `name` 存名字快照）→ 按 name 重建主键，parent 的 `$N`
//     用同表的 id→name 映射翻译，不依赖 tmux 是否活着。
//
// 迁移前整库备份一份 meta.db.bak-<时间>（meta.db 里还有蜂群注册表，一起备更安全）。
// 迁进来的行 status 先按当下 tmux 实况判，判错也无妨：Reconcile 双向自愈。
package sessmeta

import (
	"database/sql"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/storage"
)

// deadKeep 保留的死会话行数上限（超出按 died_at 从旧到新删）。
const deadKeep = 5000

// dormantCap 会话列表最多带几个休眠会话。上一代 epoch 那批本来就不会太多，
// 这个上限只是兜底：真遇上一台开了几百个会话的机器，列表不该被它淹掉。
const dormantCap = 200

type Store struct {
	HomeDir string
	// DataDir 是旧 JSON 台账所在目录（ROAM_DATA 可与 HomeDir 不同）。
	// 只在首次接管老库时用得上：metadb 的收编那一步要靠它找到 projects.json 等。
	DataDir string
	Now     func() time.Time
	// IDs 返回 {会话名 → tmux session_id}；nil 时用默认实现（直接问 tmux）。
	// 注入点主要给测试用：真实运行里默认实现就够，任何构造 Store 的地方都能正确工作。
	IDs func() map[string]string
	// Epoch 返回当前 tmux server 代次；nil 时问 tmux 要 server pid。同样是测试注入点。
	Epoch func() string
	// MemStat 给一个会话名，返回它的峰值内存（字节）与 cgroup OOM 次数。
	// 由调用方注入（Collect 用 runtime.PanePIDs + memguard 实现）——
	// 台账层不该知道 cgroup 长什么样，注入还让 Reconcile 的行为可测。
	// nil = 不采集内存，其余逻辑照常。
	MemStat func(session string) (peakRSS, oomKills int64, ok bool)

	names map[string]string // 本进程内的 name→$N 备忘（写操作后失效）
}

// Row 一行会话元数据。Session/Parent 都是**会话名**（= 持久会话 id，对外口径）。
type Row struct {
	Session    string `json:"session"`
	Parent     string `json:"parent,omitempty"`
	CreatedBy  string `json:"created_by,omitempty"`
	CreatedAt  string `json:"created_at,omitempty"`
	InitialCwd string `json:"initial_cwd,omitempty"`
	// 以下几列只在读历史时有意义，Put 不吃。
	Status     string `json:"status,omitempty"`      // live | dead
	DiedAt     string `json:"died_at,omitempty"`     //
	DiedReason string `json:"died_reason,omitempty"` // killed | host-restart
	Label      string `json:"label,omitempty"`       // 展示名快照（会话死后 @roam_name 就没了）
	Home       string `json:"home,omitempty"`        // 归属目录
	RepoRoot   string `json:"repo_root,omitempty"`   // 所属仓库根（建会话时算好的）
	AgentUUID  string `json:"agent_uuid,omitempty"`  // agent 那一侧的对话 id
	AgentKind  string `json:"agent_kind,omitempty"`  // claude | codex：恢复时敲哪个命令
	LastSeen   string `json:"last_seen,omitempty"`   // 最后一次被 Reconcile 看见（host-restart 的 died_at 取它）
}

// DisplayLabel 这一行该显示成什么名字。
//
// **兜底规则只此一份**：会话列表、休眠列表、恢复出来的新会话都用它，
// 否则就会出现「列表里叫 XiaoHui，点开恢复后变成一串裸 id」——
// 名字是现算的、没落库，两处各算各的就对不上。
//
// 恢复时算出来的名字要 SetLabel 落库（见 revive.Revive）：从那一刻起
// 它就是真名字，不再依赖谁去现算。
func (r Row) DisplayLabel() string {
	// label 等于会话 id 的，视同没起过名字。
	// recordNewSession 落库时用的是 rt.SessionLabel()，而它在没设 @roam_name 时
	// **退回会话名**——于是台账里存着一个「名字就是 id」的假名字，
	// 光判空串的话目录兜底永远不触发，列表上就是一排 2026-0812-1811-000f。
	if r.Label != "" && r.Label != r.Session {
		return r.Label
	}
	// 没显式改过名的会话（本机 17 个休眠会话里有 11 个）用归属目录名认人，
	// 比一串 2026-0812-1811-000f 强得多。
	if dir := r.Dir(); dir != "" {
		return filepath.Base(dir)
	}
	return r.Session
}

// Dir 会话的归属目录：钉死的 home 优先，退回建会话时的 cwd。
func (r Row) Dir() string {
	if r.Home != "" {
		return r.Home
	}
	return r.InitialCwd
}

func New(homeDir string) *Store { return &Store{HomeDir: homeDir, Now: time.Now} }

// WithIDs 注入会话名→$N 解析器（测试用；生产用默认的 tmux 实现）。
func (s *Store) WithIDs(f func() map[string]string) *Store {
	s.IDs, s.names = f, nil
	return s
}

func (s *Store) path() string { p, _ := metadb.ResolvePaths(s.HomeDir, s.DataDir); return p.MainPath() }

func tmuxBin() string {
	if b := os.Getenv("TMUX_BIN"); b != "" {
		return b
	}
	return "tmux"
}

// tmuxNameToID 问 tmux 要 {会话名 → session_id}。tmux 没起/出错返回 nil——
// 调用方据此进入「盲态」：不收敛、不改任何行的 status。
func tmuxNameToID() map[string]string {
	out, err := exec.Command(tmuxBin(), "list-sessions", "-F", "#{session_name}\t#{session_id}").Output()
	if err != nil {
		return nil
	}
	m := map[string]string{}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		name, id, ok := strings.Cut(strings.TrimSpace(line), "\t")
		if ok && name != "" && id != "" {
			m[name] = id
		}
	}
	return m
}

// epoch 标识「这一代 tmux server」。用 server pid：它随 server 起落而变，
// 于是能把「你手动 kill 了会话」和「机器重启把整个 server 带走了」分开记。
// pid 理论上会跨重启撞车，撞了也只是 died_reason 记成 killed，不影响任何判定。
func (s *Store) epoch() string {
	if s.Epoch != nil {
		return s.Epoch()
	}
	return tmuxServerEpoch()
}

func tmuxServerEpoch() string {
	out, err := exec.Command(tmuxBin(), "display-message", "-p", "#{pid}").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// nameToID 取（并在本进程内缓存）会话名→$N 映射。
func (s *Store) nameToID() map[string]string {
	if s.names != nil {
		return s.names
	}
	f := s.IDs
	if f == nil {
		f = tmuxNameToID
	}
	s.names = f()
	return s.names
}

// invalidate 写操作后丢掉备忘（新建会让映射变）。
func (s *Store) invalidate() { s.names = nil }

// db 取该库的共享连接。schema 与迁移都归 internal/metadb 管——原先这里自己
// 建表、自己按列名猜版本、自己 io.Copy 备份，那三件事现在全在 metadb 的版本链里。
func (s *Store) db() (*metadb.DB, error) {
	return metadb.Open(s.HomeDir, metadb.Options{DataDir: s.DataDir, Now: s.Now})
}

// Put 落一行会话元数据（按持久 id 覆盖）。会话名就是主键，不再需要问 tmux 要 `$N`
// ——于是 tmux 盲态下也记得住，不会像以前那样「这次先不记」然后永远丢了。
func (s *Store) Put(r Row) error {
	s.invalidate()
	if r.Session == "" {
		return fmt.Errorf("sessmeta: 会话名为空")
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	if r.CreatedAt == "" {
		r.CreatedAt = s.Now().Format(time.RFC3339)
	}
	// 显式列 upsert，**不能用 INSERT OR REPLACE**：那是 DELETE + INSERT，整行重置。
	// sessions 上还有 home_dir / repo_root / label 这些别处写的列，用 REPLACE 的话
	// 之后任何一次 Put（fork、plugin 建会话、adopt）都会把它们静默抹成 NULL。
	_, err = db.Exec(`INSERT INTO sessions
		(id,parent_id,created_by,created_at,initial_cwd,status,died_at,died_reason,tmux_id,tmux_epoch)
		VALUES(?,?,?,?,?,'live',NULL,NULL,NULLIF(?,''),NULLIF(?,''))
		ON CONFLICT(id) DO UPDATE SET
			parent_id=excluded.parent_id,
			created_by=excluded.created_by,
			created_at=excluded.created_at,
			initial_cwd=excluded.initial_cwd,
			status='live', died_at=NULL, died_reason=NULL,
			tmux_id=excluded.tmux_id, tmux_epoch=excluded.tmux_epoch`,
		r.Session, nullable(r.Parent), r.CreatedBy, r.CreatedAt, r.InitialCwd,
		s.nameToID()[r.Session], s.epoch())
	return err
}

// SetHome 记会话的**归属目录台账事实**（键是持久会话 id，会话死了也要留着）。
//
// 它和后端那张 session_homes 表分工不同：那张的键是 tmux `$N`，pane 一死就收敛，
// 是运行时绑定；这一列是台账，M3 的「已结束的会话」和「重开」都要靠它。
// repoRoot 是建会话那一刻算出来的仓库根——worktree 事后会被删掉，
// 那时再从目录反推就永远推不出来了，所以要在事实还可知的时候记下来。
func (s *Store) SetHome(session, home, repoRoot string) error {
	if session == "" {
		return fmt.Errorf("sessmeta: 会话名为空")
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	_, err = db.Exec(`INSERT INTO sessions(id,created_by,created_at,home_dir,repo_root)
		VALUES(?,'adopt',?,NULLIF(?,''),NULLIF(?,''))
		ON CONFLICT(id) DO UPDATE SET
			home_dir=COALESCE(NULLIF(excluded.home_dir,''), home_dir),
			repo_root=COALESCE(NULLIF(excluded.repo_root,''), repo_root)`,
		session, s.Now().Format(time.RFC3339), home, repoRoot)
	return err
}

// SetLabel 记展示名快照。会话一死 tmux 的 @roam_name 就没了，而历史列表还要显示它。
func (s *Store) SetLabel(session, label string) error {
	if session == "" || label == "" {
		return nil
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	_, err = db.Exec(`UPDATE sessions SET label=? WHERE id=?`, label, session)
	return err
}

// Get 读单个会话的台账行（活的死的都能读）。
func (s *Store) Get(session string) (Row, bool) {
	if session == "" {
		return Row{}, false
	}
	db, err := s.db()
	if err != nil {
		return Row{}, false
	}
	r := Row{Session: session}
	err = db.QueryRow(`SELECT IFNULL(parent_id,''), IFNULL(created_by,''), IFNULL(created_at,''),
		IFNULL(initial_cwd,''), status, IFNULL(died_at,''), IFNULL(died_reason,''),
		IFNULL(label,''), IFNULL(home_dir,''), IFNULL(repo_root,''), IFNULL(agent_session_uuid,''),
		IFNULL(agent_kind,'')
		FROM sessions WHERE id=?`, session).
		Scan(&r.Parent, &r.CreatedBy, &r.CreatedAt, &r.InitialCwd, &r.Status,
			&r.DiedAt, &r.DiedReason, &r.Label, &r.Home, &r.RepoRoot, &r.AgentUUID, &r.AgentKind)
	return r, err == nil
}

// SetRestoredFrom 记「这个会话是谁重开出来的」。旧行保持 dead 不复活——
// 重开的是壳不是现场，历史不该被改写。
func (s *Store) SetRestoredFrom(session, from string) error {
	if session == "" || from == "" {
		return nil
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	_, err = db.Exec(`UPDATE sessions SET restored_from=? WHERE id=?`, from, session)
	return err
}

// SetAgentSession 记 agent 那一侧的对话 id（Claude Code 的 <uuid>.jsonl）。
// 拉起 agent 时传了 --session-id，这里把同一个 uuid 落进台账——「重开并接回原对话」
// 全靠它，而它必须在会话还活着的时候记下来。
// **只记一次，不覆盖**：一个会话里可能先后跑过好几段 claude，我们要的是它自己
// 那一段的起点；而上层的关联多少带点推断成分，覆盖只会让先前确定的那次变得不确定。
func (s *Store) SetAgentSession(session, uuid string) error {
	if session == "" || uuid == "" {
		return nil
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	_, err = db.Exec(`UPDATE sessions SET agent_session_uuid=?
		WHERE id=? AND IFNULL(agent_session_uuid,'')=''`, uuid, session)
	return err
}

// SetParent 设置/清空 parent；设置前做环检测（沿新父链上溯不得遇到 child）。
func (s *Store) SetParent(child, parent string) error {
	s.invalidate()
	if child == "" {
		return fmt.Errorf("sessmeta: 会话名为空")
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	for cur, depth := parent, 0; cur != "" && depth < 100; depth++ {
		if cur == child {
			return fmt.Errorf("parent cycle: %s is an ancestor of itself", child)
		}
		var next sql.NullString
		if err := db.QueryRow(`SELECT parent_id FROM sessions WHERE id=?`, cur).Scan(&next); err != nil {
			break // 无记录 = 顶层，链到头
		}
		cur = next.String
	}
	// child 可能还没有行（tmux 直建的会话被收编）：UPSERT
	_, err = db.Exec(`INSERT INTO sessions(id,parent_id,created_by,created_at) VALUES(?,?,'adopt',?)
		ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id`,
		child, nullable(parent), s.Now().Format(time.RFC3339))
	return err
}

// Parent 返回会话的父**会话名**（无记录/无父返回空串）。父会话可能已经死了——
// 那也照样返回：它是这个会话的来历，不因为对方死掉就不成立。
func (s *Store) Parent(session string) string {
	if session == "" {
		return ""
	}
	db, err := s.db()
	if err != nil {
		return ""
	}
	var pid sql.NullString
	if db.QueryRow(`SELECT parent_id FROM sessions WHERE id=?`, session).Scan(&pid) != nil {
		return ""
	}
	return pid.String
}

// Children 返回**still alive** 的直接子会话名。级联杀、树投影都只该看活的。
func (s *Store) Children(parent string) []string {
	if parent == "" {
		return nil
	}
	db, err := s.db()
	if err != nil {
		return nil
	}
	rows, err := db.Query(`SELECT id FROM sessions WHERE parent_id=? AND status='live'`, parent)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var cid string
		if rows.Scan(&cid) == nil && cid != "" {
			out = append(out, cid)
		}
	}
	sort.Strings(out)
	return out
}

// All 返回活会话（key = 会话名，供 ls --tree 投影）。父会话已死的行按孤儿投影：
// 只在投影里断链，表里的来历不动——「谁 fork 出了我」是历史，不该被父亲的死改写。
//
// 判父亲死活看 **tmux 实况**而不是「表里有没有活行」：父会话常常是 `roami session new`
// 直建的、压根没有自己的行（只有 fork 出来的孩子才写行），按行判会把整棵树拍平。
func (s *Store) All() map[string]Row {
	db, err := s.db()
	if err != nil {
		return nil
	}
	rows, err := db.Query(`SELECT id, IFNULL(parent_id,''), IFNULL(created_by,''),
		IFNULL(created_at,''), IFNULL(initial_cwd,'') FROM sessions WHERE status='live'`)
	if err != nil {
		return nil
	}
	out := map[string]Row{}
	for rows.Next() {
		var r Row
		if rows.Scan(&r.Session, &r.Parent, &r.CreatedBy, &r.CreatedAt, &r.InitialCwd) == nil {
			out[r.Session] = r
		}
	}
	rows.Close()
	alive := s.nameToID()
	if alive == nil { // 盲态：照记录返回，不猜谁死了
		return out
	}
	for name, r := range out {
		if _, ok := alive[r.Parent]; r.Parent != "" && !ok {
			r.Parent = ""
			out[name] = r
		}
	}
	return out
}

// History 返回已结束的会话，新的在前（limit<=0 表示不限）。会话历史是用户数据：
// 日志还在 logs/<id>.log，这张表是找回它们的唯一索引。
func (s *Store) History(limit int) []Row {
	db, err := s.db()
	if err != nil {
		return nil
	}
	q := `SELECT id, IFNULL(parent_id,''), IFNULL(created_by,''), IFNULL(created_at,''),
		IFNULL(initial_cwd,''), IFNULL(died_at,''), IFNULL(died_reason,''),
		IFNULL(label,''), IFNULL(home_dir,''), IFNULL(repo_root,''), IFNULL(agent_session_uuid,'')
		FROM sessions WHERE status='dead' ORDER BY IFNULL(died_at,created_at) DESC`
	args := []any{}
	if limit > 0 {
		q += ` LIMIT ?`
		args = append(args, limit)
	}
	rows, err := db.Query(q, args...)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []Row
	for rows.Next() {
		r := Row{Status: "dead"}
		if rows.Scan(&r.Session, &r.Parent, &r.CreatedBy, &r.CreatedAt, &r.InitialCwd,
			&r.DiedAt, &r.DiedReason, &r.Label, &r.Home, &r.RepoRoot, &r.AgentUUID) == nil {
			out = append(out, r)
		}
	}
	return out
}

// Dormant 返回「休眠」会话：机器重启带走了，但随时可以点开重来的那些。
//
// 会话的「在」和「活」是两件事——「在」（目录、名字、对话 id）一直在台账里，
// 重启带不走；「活」（tmux 会话和 pane 里的进程）确实没了。列表要显示的是
// 「在」的全集，所以这批得跟活会话一起出现在 ls 里，用户点哪个哪个才真正起来。
//
// 筛选条件一个都不能少，每一条都对应一类实测出来的噪音：
//
//   - died_reason='host-restart'：你**显式 kill** 的会话就该是死的，
//     它在列表里再冒出来比消失更让人恼火。
//   - 只取**上一代 tmux server**（最新的那个 tmux_epoch）带走的那批。
//     不加这条就是「历史上所有被重启带走过的会话」——本机实测 73 条，
//     混着七月份的测试会话和早就删掉的 /tmp 目录。上上次重启带走、
//     隔了这么久都没去恢复的，本来就不需要了，留在列表里只是噪音。
//   - tmux_epoch 非空：迁移前的老行没记 epoch（本机 150 条），
//     判不出属于哪次重启，一律不认。
//   - restored_from 没被占用：已经重开过的不再出现，否则点一次多一个。
//   - 有归属目录，且**目录还在**：worktree 被清是常事，无处可开的不该出现在
//     列表里诱人点一下（目录存在性在 Go 侧查，SQL 做不到）。
//
// 见 docs/design/reliability/session-restore.html。
func (s *Store) Dormant() []Row {
	db, err := s.db()
	if err != nil {
		return nil
	}
	rows, err := db.Query(`SELECT d.id, IFNULL(d.created_at,''), IFNULL(d.initial_cwd,''),
		IFNULL(d.died_at,''), IFNULL(d.label,''), IFNULL(d.home_dir,''),
		IFNULL(d.repo_root,''), IFNULL(d.agent_session_uuid,''), IFNULL(d.agent_kind,'')
		FROM sessions d
		WHERE d.status='dead' AND d.died_reason='host-restart'
		  AND IFNULL(d.tmux_epoch,'') <> ''
		  AND d.tmux_epoch = (SELECT tmux_epoch FROM sessions
		        WHERE status='dead' AND died_reason='host-restart' AND IFNULL(tmux_epoch,'') <> ''
		        ORDER BY IFNULL(died_at,created_at) DESC LIMIT 1)
		  AND IFNULL(d.home_dir,IFNULL(d.initial_cwd,'')) <> ''
		  AND NOT EXISTS (SELECT 1 FROM sessions r WHERE r.restored_from = d.id)
		ORDER BY IFNULL(d.died_at,d.created_at) DESC
		LIMIT ?`, dormantCap)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []Row
	for rows.Next() {
		r := Row{Status: "dead", DiedReason: "host-restart"}
		if rows.Scan(&r.Session, &r.CreatedAt, &r.InitialCwd, &r.DiedAt,
			&r.Label, &r.Home, &r.RepoRoot, &r.AgentUUID, &r.AgentKind) != nil {
			continue
		}
		dir := r.Home
		if dir == "" {
			dir = r.InitialCwd
		}
		if fi, err := os.Stat(dir); err != nil || !fi.IsDir() {
			continue
		}
		out = append(out, r)
	}
	return out
}

// RestoredAs 反查一个休眠会话已经被重开成了哪个会话（没有则空串）。
// 它是懒恢复的幂等键：点两次不该长出两个会话。
func (s *Store) RestoredAs(dormant string) string {
	if dormant == "" {
		return ""
	}
	db, err := s.db()
	if err != nil {
		return ""
	}
	var id string
	// 同一行理论上只会被重开一次；真出现多行（并发穿透）也取最新那个，
	// 让调用方收敛到同一个会话上，而不是随机挑一个。
	if db.QueryRow(`SELECT id FROM sessions WHERE restored_from=?
		ORDER BY IFNULL(created_at,'') DESC LIMIT 1`, dormant).Scan(&id) != nil {
		return ""
	}
	return id
}

// SetAgentKind 记这个会话跑的是哪种 agent（claude / codex）。
// 恢复时靠它决定敲什么命令；**只记一次不覆盖**，理由同 SetAgentSession。
func (s *Store) SetAgentKind(session, kind string) error {
	if session == "" || kind == "" {
		return nil
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	_, err = db.Exec(`UPDATE sessions SET agent_kind=?
		WHERE id=? AND IFNULL(agent_kind,'')=''`, kind, session)
	return err
}

// OnRename 会话名变了 → 主键跟着搬（连带所有指向它的 parent_id）。
//
// 日常改名只动 @roam_name 展示名，会话名（= 持久 id）不动，这个入口就是空转。
// 它存在是为了 `runtime.MigrateSessionsToID` 那类**真的重命名 tmux 会话**的一次性
// 迁移：主键既然是会话名，handle 一变表就必须跟着走，否则那行当场变孤魂。
func (s *Store) OnRename(old, neu string) error {
	s.invalidate()
	if old == "" || neu == "" || old == neu {
		return nil
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.Exec(`UPDATE sessions SET id=? WHERE id=?`, neu, old); err != nil {
		return err
	}
	if _, err := tx.Exec(`UPDATE sessions SET parent_id=? WHERE parent_id=?`, neu, old); err != nil {
		return err
	}
	return tx.Commit()
}

// OnKill 会话被杀：置 dead，不删行。直接孩子不动 parent——孤儿收养在 All() 的
// 投影里完成，表里保住「谁 fork 出了谁」。
func (s *Store) OnKill(session string) error {
	s.invalidate()
	if session == "" {
		return nil
	}
	db, err := s.db()
	if err != nil {
		return err
	}
	_, err = db.Exec(`UPDATE sessions SET status='dead', died_at=?, died_reason='killed', tmux_id=NULL
		WHERE id=? AND status='live'`, s.Now().Format(time.RFC3339), session)
	return err
}

// Reconcile 对齐 tmux 实况，**双向**自愈：活着的置 live 并刷新运行时句柄，不在了
// 的置 dead（不删）。alive 为空（tmux 盲态）时一行不动——看不见的时候不下判断。
// server 确定不在的情况不走这里，走 ReconcileServerGone。
//
// died_reason 分两种：tmux_epoch 还是这一代 server ⇒ 是被杀的；对不上 ⇒ server
// 换代了（机器重启把它带走的）。这是「重启后一整批会话集体消失」和「你刚 kill 了
// 一个」在台账里唯一的区别，排障时很值钱。
func (s *Store) Reconcile(alive map[string]bool) {
	if len(alive) == 0 {
		return
	}
	ids := s.nameToID()
	if len(ids) == 0 {
		return
	}
	db, err := s.db()
	if err != nil {
		return
	}
	epoch := s.epoch()
	now := s.Now().Format(time.RFC3339)
	// 活着的时候就把「最后一次看见」和峰值内存记下来。
	//
	// died_at 从前一律取「现在」，而 Reconcile 是开机后才跑的——于是重启带走的
	// 那一批全部记成开机时刻，跟真实结束时刻差了整整一夜（本机 17 条都是 10:43:33）。
	// peak_rss 同理：会话一没，cgroup 目录跟着消失，那时再问已经晚了。
	for name := range alive {
		if s.MemStat == nil {
			break
		}
		peak, ooms, ok := s.MemStat(name)
		if !ok {
			continue
		}
		// peak / oom 计数都取历史最大：cgroup 的 memory.peak 本身就是峰值，
		// 但会话可能跨过一次 revive，别让新一段的低水位把旧记录抹掉。
		_, _ = db.Exec(`UPDATE sessions SET peak_rss=MAX(IFNULL(peak_rss,0),?),
			oom_kills=MAX(IFNULL(oom_kills,0),?) WHERE id=?`, peak, ooms, name)
	}
	for name := range alive {
		_, _ = db.Exec(`UPDATE sessions SET last_seen=? WHERE id=? AND status='live'`, now, name)
	}

	for name := range alive {
		id, ok := ids[name]
		if !ok {
			continue
		}
		// 死行上又冒出同名会话 = 一个**新**会话（会话名能复用的只剩 `_ttmux-*` 这类
		// 固定名单例和插件会话）。复活它，但旧来历一律不继承——否则新会话平白多出
		// 一个爹、一个别人的起始目录。代价是那条历史被顶掉，M2 的 session_runs 会补。
		_, _ = db.Exec(`UPDATE sessions SET status='live', died_at=NULL, died_reason=NULL,
			parent_id=NULL, created_by='reuse', created_at=?, initial_cwd=NULL,
			tmux_id=?, tmux_epoch=NULLIF(?,'') WHERE id=? AND status='dead'`, now, id, epoch, name)
		_, _ = db.Exec(`UPDATE sessions SET tmux_id=?, tmux_epoch=NULLIF(?,'')
			WHERE id=? AND status='live'`, id, epoch, name)
	}
	// oom_kills 读的是**上一轮采集**落下的值：cgroup 目录随会话一起消失，
	// 等发现它没了再去读已经晚了（实测 scope 当场就没）。
	//
	// 局限说清楚：如果 OOM 把 shell 也一起带走、且两次 Reconcile 之间没采到，
	// 这一条会退回记成 killed。主场景（失控的 agent 被杀、shell 和会话都还活着）
	// 采得到，因为会话还在，下一轮照常遍历它。
	rows, err := db.Query(`SELECT id, IFNULL(tmux_epoch,''), IFNULL(last_seen,''), IFNULL(oom_kills,0)
		FROM sessions WHERE status='live'`)
	if err != nil {
		return
	}
	type goner struct{ id, reason, at string }
	var dead []goner
	for rows.Next() {
		var id, was, seen string
		var ooms int64
		if rows.Scan(&id, &was, &seen, &ooms) != nil || alive[id] {
			continue
		}
		reason, at := "killed", now
		switch {
		case ooms > 0:
			// 撞了自己的内存上限：cgroup 在这个 scope 里选 victim 杀掉了它。
			// 这一条最值钱——下次「机器怎么又卡了」不用再去翻内核 OOM dump。
			reason = "oom"
		case was != "" && epoch != "" && was != epoch:
			// server 换代了 = 机器重启把它带走的。真实结束时刻是最后一次看见它，
			// 不是「现在」（现在是开机后第一次 Reconcile，晚了一整夜）。
			reason = "host-restart"
			if seen != "" {
				at = seen
			}
		}
		dead = append(dead, goner{id, reason, at})
	}
	rows.Close()
	for _, g := range dead {
		_, _ = db.Exec(`UPDATE sessions SET status='dead', died_at=?, died_reason=?, tmux_id=NULL
			WHERE id=?`, g.at, g.reason, g.id)
	}
	s.prune(db, deadKeep)
}

// ReconcileServerGone 处理 tmux server **确定不在**的情况（socket 连不上，见 runtime.NoServer）。
//
// 这不是盲态。盲态是「看不见」，这里是「看清楚了，一个都不在」——机器重启、
// tmux 被整个带走之后就是这样。Reconcile 在 alive 为空时一行不动，于是重启后
// 所有行卡在 live：Dormant() 只认 dead 行，列表里一个休眠会话都不出现，
// 要等用户随手新建一个会话、alive 非空了才被收敛（实测就是「点了新建命令行
// 旧会话才冒出来」）。这里把所有 live 行一次收进历史，记 host-restart（整批一起
// 没的，不是谁被 kill），died_at 取最后一次看见它。tmux_epoch 原样留着，
// Dormant() 靠它认「上一代 server 带走的那批」。
func (s *Store) ReconcileServerGone() {
	db, err := s.db()
	if err != nil {
		return
	}
	now := s.Now().Format(time.RFC3339)
	_, _ = db.Exec(`UPDATE sessions SET status='dead', died_reason='host-restart', tmux_id=NULL,
		died_at=CASE WHEN IFNULL(last_seen,'')<>'' THEN last_seen ELSE ? END
		WHERE status='live'`, now)
	s.prune(db, deadKeep)
}

// prune 死行超上限就按 died_at 从旧到新删，读放大有界。
func (s *Store) prune(db *metadb.DB, keep int) {
	if keep <= 0 {
		return
	}
	_, _ = db.Exec(`DELETE FROM sessions WHERE status='dead' AND id NOT IN (
		SELECT id FROM sessions WHERE status='dead'
		ORDER BY IFNULL(died_at,created_at) DESC LIMIT ?)`, keep)
}

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}
