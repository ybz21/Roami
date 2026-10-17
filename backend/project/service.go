// Package project 实现项目的弱台账（knownRepos）与 UI 偏好持久化
// （<dataDir>/projects.json，08 设计 §2.1/§5.2）。项目本身是读模型：发现 = 会话
// 归属目录 join 的副作用（api 层聚合时 Touch），退场 = 读时收敛；git/session 真相源
// 不在此——文件丢失只损失「零会话仓库的可发现性」与置顶等偏好，活跃仓库下次
// 开会话即重建。
//
// 身份 = 入册时生成的不可变 id（internal/id，与蜂群同款可读格式），目录只是可变
// 属性。历史版本用「目录名 slug + 路径 hash」当 key，`mv` 一下目录身份就变、偏好
// 得靠合并搬家；现在换 id 后目录随便挪，老 key 落进 aliases 继续解析老链接。
package project

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/id"
	"github.com/ybz21/Roami/internal/metadb"
)

// Prefs 是项目的 UI 偏好（PATCH /projects/:key/prefs 可改）。
type Prefs struct {
	Pinned       bool   `json:"pinned,omitempty"`
	DisplayName  string `json:"displayName,omitempty"`
	DefaultAgent string `json:"defaultAgent,omitempty"`
	DefaultBase  string `json:"defaultBase,omitempty"`
}

// Entry 是台账里的一个项目。**身份是 ID，不是目录**：ID 入册时生成、永不变，
// Dir 只是可变属性（`mv` 项目目录、worktree 子目录归位主仓库根都只改 Dir，
// 置顶/显示名/默认 agent 等偏好一个不丢）。Dir 为 canonical 目录（git 项目 =
// 主仓库根，来自 annotation 的 Repo 或显式创建时的 ResolveRepo）。
// Origin 区分两条入册通道：
//   - "user"：用户显式创建（POST /projects）——一等对象，永不自动退场，只能显式 DELETE；
//   - ""（discovered）：会话归属目录 join 自动发现——按退场规则读时收敛。
type Entry struct {
	ID     string `json:"id"`
	Dir    string `json:"dir"`
	Origin string `json:"origin,omitempty"`
	Prefs
	FirstSeen int64 `json:"firstSeen"`
	LastSeen  int64 `json:"lastSeen"`
	// LastSessionAt 最后一次在这个项目里见到会话的时刻。退场规则看它而不是「此刻
	// 有几个会话」：机器一重启 tmux 全清零，按当下会话数收敛会把所有发现型项目
	// 一次性删光（会话是运行时，项目是台账，不能让前者的生死决定后者的存亡）。
	LastSessionAt int64 `json:"lastSessionAt,omitempty"`
	// ArchivedAt 归档时刻（0 = 在册）。「干过活但此刻空着」的项目转到这里，
	// 而不是继续和活跃项目挤在同一份列表里——它们只是没开会话，不是没了。
	// 一旦又开了会话就自动回到活跃。
	ArchivedAt int64 `json:"archivedAt,omitempty"`
}

type fileShape struct {
	Repos map[string]*Entry `json:"repos"`
	// Aliases 老 key → id：v1 文件的 key 是「目录名 slug + 路径 hash」，迁移后
	// 老书签 `#/projects/<老key>` 和外部链接仍要能打开；合并掉的 id 也记在这。
	Aliases map[string]string `json:"aliases,omitempty"`
}

// Store 单写者：所有变更持内存互斥锁，落盘 tmp+rename 原子替换（同 RaceStore 体例）。
type Store struct {
	mu      sync.Mutex
	path    string            // 旧 JSON 台账；只在降级模式下写
	db      *metadb.DB        // 直连模式下的真相源
	repos   map[string]*Entry // id → 条目
	aliases map[string]string // 老 key / 被合并的 id → 现行 id
	byDir   map[string]string // dir → id（查重索引，替代原先的路径 hash key）
}

// NewStore 建台账。db 直连可用时以库为准，否则退回旧的 projects.json。
//
// 台账整体仍是**内存模型 + 落盘**：项目是几十条的量级，读全在内存里，
// 换存储只换了 load/save 两端。这样 mergeInto/resolve/退场判定/60s 节流
// 这些语义一行没动，出了问题也只可能出在持久化这一层。
func NewStore(dataDir string, db *metadb.DB) *Store {
	s := &Store{repos: map[string]*Entry{}, aliases: map[string]string{}, byDir: map[string]string{}, db: db}
	if db.OK() {
		s.loadDB()
		return s
	}
	if dataDir != "" {
		s.path = filepath.Join(dataDir, "projects.json")
		if b, err := os.ReadFile(s.path); err == nil {
			var f fileShape
			if json.Unmarshal(b, &f) == nil {
				s.load(f)
			}
		}
	}
	return s
}

// loadDB 从库里读全量（调用方不持锁——只在构造时调）。
func (s *Store) loadDB() {
	rows, err := s.db.Query(`SELECT id, dir, IFNULL(origin,''), IFNULL(display_name,''),
		IFNULL(pinned,0), IFNULL(default_agent,''), IFNULL(default_base,''),
		IFNULL(first_seen,0), IFNULL(last_seen,0), IFNULL(last_session_at,0),
		IFNULL(archived_at,0) FROM projects`)
	if err != nil {
		return
	}
	for rows.Next() {
		var e Entry
		var pinned int
		if rows.Scan(&e.ID, &e.Dir, &e.Origin, &e.DisplayName, &pinned, &e.DefaultAgent,
			&e.DefaultBase, &e.FirstSeen, &e.LastSeen, &e.LastSessionAt, &e.ArchivedAt) != nil {
			continue
		}
		e.Pinned = pinned != 0
		cp := e
		s.repos[e.ID] = &cp
		s.byDir[e.Dir] = e.ID
	}
	rows.Close()
	arows, err := s.db.Query(`SELECT alias, project_id FROM project_aliases`)
	if err != nil {
		return
	}
	defer arows.Close()
	for arows.Next() {
		var a, id string
		if arows.Scan(&a, &id) == nil {
			s.aliases[a] = id
		}
	}
}

// saveDB 把内存台账写回库（调用方须持锁）。
//
// 整表 upsert + 删掉不在内存里的行——不是「先清空再插」：那样会让
// project_aliases 的 ON DELETE CASCADE 把别名一起删掉，老书签当场失效。
func (s *Store) saveDB() {
	err := s.db.Tx(func(tx *sql.Tx) error {
		keep := make([]any, 0, len(s.repos))
		for id, e := range s.repos {
			if _, err := tx.Exec(`INSERT INTO projects
				(id,dir,origin,display_name,pinned,default_agent,default_base,
				 first_seen,last_seen,last_session_at,archived_at)
				VALUES(?,?,?,?,?,?,?,?,?,?,?)
				ON CONFLICT(id) DO UPDATE SET dir=excluded.dir, origin=excluded.origin,
					display_name=excluded.display_name, pinned=excluded.pinned,
					default_agent=excluded.default_agent, default_base=excluded.default_base,
					first_seen=excluded.first_seen, last_seen=excluded.last_seen,
					last_session_at=excluded.last_session_at, archived_at=excluded.archived_at`,
				e.ID, e.Dir, e.Origin, e.DisplayName, boolInt(e.Pinned), e.DefaultAgent,
				e.DefaultBase, e.FirstSeen, e.LastSeen, e.LastSessionAt, e.ArchivedAt); err != nil {
				return err
			}
			keep = append(keep, id)
		}
		if err := deleteMissing(tx, "projects", "id", keep); err != nil {
			return err
		}
		aliases := make([]any, 0, len(s.aliases))
		for a, id := range s.aliases {
			if _, err := tx.Exec(`INSERT INTO project_aliases(alias,project_id)
				SELECT ?, id FROM projects WHERE id=?
				ON CONFLICT(alias) DO UPDATE SET project_id=excluded.project_id`, a, id); err != nil {
				return err
			}
			aliases = append(aliases, a)
		}
		return deleteMissing(tx, "project_aliases", "alias", aliases)
	})
	if err != nil {
		log.Printf("项目台账写库失败: %v", err)
	}
}

// deleteMissing 删掉 keep 之外的行。keep 为空时清表。
func deleteMissing(tx *sql.Tx, table, key string, keep []any) error {
	if len(keep) == 0 {
		_, err := tx.Exec(`DELETE FROM ` + table)
		return err
	}
	ph := strings.TrimSuffix(strings.Repeat("?,", len(keep)), ",")
	_, err := tx.Exec(`DELETE FROM `+table+` WHERE `+key+` NOT IN (`+ph+`)`, keep...)
	return err
}

func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// load 读入文件并就地迁移 v1（key = 路径派生 hash）→ v2（key = 不可变 id）。
// 迁移只发生一次：老 key 记进 aliases，之后照常按 id 读写。
func (s *Store) load(f fileShape) {
	for k, v := range f.Aliases {
		s.aliases[k] = v
	}
	migrated := false
	keys := make([]string, 0, len(f.Repos))
	for k := range f.Repos {
		keys = append(keys, k)
	}
	sort.Strings(keys) // 定序：同目录重复条目谁留下、谁并进去，不随 map 迭代序漂
	for _, key := range keys {
		e := f.Repos[key]
		if e == nil || e.Dir == "" {
			continue
		}
		if cur, dup := s.byDir[e.Dir]; dup { // 同目录重复条目（历史脏数据）→ 合并，别留两份
			mergeInto(s.repos[cur], e)
			s.aliases[key] = cur
			migrated = true
			continue
		}
		newKey := key
		if !id.Valid(key) || e.ID != key { // v1 条目：发 id，老 key 留作别名
			newKey = id.New()
			s.aliases[key] = newKey
			migrated = true
		}
		e.ID = newKey
		s.repos[newKey] = e
		s.byDir[e.Dir] = newKey
	}
	if migrated {
		s.save()
	}
}

// mergeInto 把 src 的「用户意志」并进 dst（or 语义：置顶/显式创建/显示名/最早 firstSeen）。
func mergeInto(dst, src *Entry) {
	if dst == nil || src == nil {
		return
	}
	dst.Pinned = dst.Pinned || src.Pinned
	if dst.Origin == "" {
		dst.Origin = src.Origin
	}
	if dst.DisplayName == "" {
		dst.DisplayName = src.DisplayName
	}
	if dst.DefaultAgent == "" {
		dst.DefaultAgent = src.DefaultAgent
	}
	if dst.DefaultBase == "" {
		dst.DefaultBase = src.DefaultBase
	}
	if src.FirstSeen > 0 && (dst.FirstSeen == 0 || src.FirstSeen < dst.FirstSeen) {
		dst.FirstSeen = src.FirstSeen
	}
	if src.LastSeen > dst.LastSeen {
		dst.LastSeen = src.LastSeen
	}
}

// save 持久化全量（调用方须持锁）。
func (s *Store) save() {
	if s.db.OK() {
		s.saveDB()
		return
	}
	if s.path == "" {
		return
	}
	b, err := json.MarshalIndent(fileShape{Repos: s.repos, Aliases: s.aliases}, "", "  ")
	if err != nil {
		return
	}
	tmp := s.path + ".tmp"
	if os.WriteFile(tmp, b, 0o600) == nil {
		_ = os.Rename(tmp, s.path)
	}
}

// resolve 把「id 或老 key」解析成现行 id（调用方须持锁）；解析不到返回 ""。
func (s *Store) resolve(key string) string {
	if _, ok := s.repos[key]; ok {
		return key
	}
	if to, ok := s.aliases[key]; ok {
		if _, live := s.repos[to]; live {
			return to
		}
	}
	return ""
}

// Touch 发现记账：不在册则记入（FirstSeen），在册则刷新 LastSeen。返回项目 id。
func (s *Store) Touch(dir string) string {
	if dir == "" {
		return ""
	}
	now := time.Now().Unix()
	s.mu.Lock()
	defer s.mu.Unlock()
	if key, ok := s.byDir[dir]; ok {
		e := s.repos[key]
		if now-e.LastSeen >= 60 { // LastSeen 只按分钟粒度刷新，避免每次轮询都写盘
			e.LastSeen = now
			s.save()
		}
		return key
	}
	key := id.New()
	s.repos[key] = &Entry{ID: key, Dir: dir, FirstSeen: now, LastSeen: now}
	s.byDir[dir] = key
	s.save()
	return key
}

// Add 显式创建（POST /projects）：origin=user 的一等对象。目录已在册则升级为 user
// （发现来的条目被用户「转正」，id 不变）。返回项目 id 和「是不是新建的」。
//
// 显示名只在新建、或原来没起过名时写：已有项目再「新建」一次（典型是从它的某个
// worktree 目录建——ResolveRepo 归位到同一个仓库根），传来的名字是给那个 worktree 起的，
// 不该把项目本来的名字盖掉（blade-agent 就这么被改成了 blade-agent-sea-attack）。
func (s *Store) Add(dir, displayName string) (key string, created bool) {
	if dir == "" {
		return "", false
	}
	now := time.Now().Unix()
	s.mu.Lock()
	defer s.mu.Unlock()
	key, ok := s.byDir[dir]
	if !ok {
		key = id.New()
		s.repos[key] = &Entry{ID: key, Dir: dir, FirstSeen: now}
		s.byDir[dir] = key
	}
	e := s.repos[key]
	e.Origin = "user"
	e.LastSeen = now
	if displayName != "" && (!ok || e.DisplayName == "") {
		e.DisplayName = displayName
	}
	s.save()
	return key, !ok
}

// Name 项目的显示名（没起过就是目录名）；不在册返回空。
func (s *Store) Name(key string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	e, ok := s.repos[s.resolve(key)]
	if !ok {
		return ""
	}
	if e.DisplayName != "" {
		return e.DisplayName
	}
	return filepath.Base(e.Dir)
}

// NoteSessions 记「这个项目此刻有会话」。聚合层每轮算完会话数调一次，
// 退场判定据此区分「从来没干过活」和「干过，只是现在没开着」。
func (s *Store) NoteSessions(key string) {
	now := time.Now().Unix()
	s.mu.Lock()
	defer s.mu.Unlock()
	k := s.resolve(key)
	if k == "" {
		return
	}
	if now-s.repos[k].LastSessionAt >= 60 { // 同 LastSeen：分钟粒度，别每轮都写盘
		s.repos[k].LastSessionAt = now
		s.save()
	}
}

// SetArchived 置/清归档。归档是**读时收敛的判定结果**，不是用户动作：
// 聚合层每轮算完就把它写回来，所以只在真的变了的时候落盘。
func (s *Store) SetArchived(key string, at int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := s.resolve(key)
	if k == "" || s.repos[k].ArchivedAt == at {
		return
	}
	s.repos[k].ArchivedAt = at
	s.save()
}

// Entries 返回台账快照（copy，key = 项目 id，供只读聚合遍历）。
func (s *Store) Entries() map[string]Entry {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make(map[string]Entry, len(s.repos))
	for k, e := range s.repos {
		out[k] = *e
	}
	return out
}

// Dir 反查 id（或老 key）→ 目录。API 只接受在册 key，顺带杜绝任意路径探测。
func (s *Store) Dir(key string) (string, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := s.resolve(key)
	if k == "" {
		return "", false
	}
	return s.repos[k].Dir, true
}

// SetPrefs 原子改偏好；key 不在册返回 false。
func (s *Store) SetPrefs(key string, patch func(*Prefs)) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := s.resolve(key)
	if k == "" {
		return false
	}
	patch(&s.repos[k].Prefs)
	s.save()
	return true
}

// Remove 退场收敛（目录不存在，或 无 roam worktree ∧ 无会话 ∧ 未置顶——判定在聚合层）。
func (s *Store) Remove(key string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := s.resolve(key)
	if k == "" {
		return
	}
	delete(s.byDir, s.repos[k].Dir)
	delete(s.repos, k)
	for alias, to := range s.aliases { // 指向已删条目的别名一并清掉，别留悬空
		if to == k {
			delete(s.aliases, alias)
		}
	}
	s.save()
}

// ── 收尾留痕（08 §5.2）：<dataDir>/activity.log JSONL，只增不改 ──
// 不是任务真相源——丢弃删除后的提交不可达，留痕只保住「任务→动作→统计」的摘要。

// TraceEntry 一条收尾留痕。Action: merged | discarded | cleaned。
// ID 由 Trace 写入时生成（与项目/竞赛/蜂群同款可读 id），老行没有这个字段。
type TraceEntry struct {
	ID       string `json:"id,omitempty"`
	Repo     string `json:"repo"`
	Branch   string `json:"branch"`
	HeadOid  string `json:"headOid,omitempty"`
	Base     string `json:"base,omitempty"`
	Action   string `json:"action"`
	Strategy string `json:"strategy,omitempty"`
	At       int64  `json:"at"`
	// 合入检测补充（10 设计 §5）：cleaned 动作记录检出的合入目标与方式，
	// 让「任务 → 已在主干」的映射在 worktree 删除后仍可追溯。
	MergedInto string `json:"mergedInto,omitempty"`
	MergedKind string `json:"mergedKind,omitempty"`
}

func (s *Store) tracePath() string {
	if s.path == "" {
		return ""
	}
	return filepath.Join(filepath.Dir(s.path), "activity.log")
}

// Trace 记一条留痕。写失败只丢摘要，不影响主流程。
func (s *Store) Trace(e TraceEntry) {
	e.At = time.Now().Unix()
	if e.ID == "" {
		e.ID = id.New()
	}
	if s.db.OK() {
		s.traceDB(e)
		return
	}
	s.traceFile(e)
}

// traceDB 落库，并把这个仓库的留痕修剪到 traceKeep 条。
//
// 文件形态靠「5MB 轮转一代」给读放大封顶；进了库那条机制就没了，可留痕仍是只增的。
// 按仓库各留最近 traceKeep 条：修剪只在写时发生（合入/丢弃/清理都是人的动作，稀疏），
// 而项目活动页要的永远是最近那几十条。
func (s *Store) traceDB(e TraceEntry) {
	if _, err := s.db.Exec(`INSERT OR REPLACE INTO project_traces
		(id,repo,branch,head_oid,base,action,strategy,at,merged_into,merged_kind)
		VALUES(?,?,?,?,?,?,?,?,?,?)`,
		e.ID, e.Repo, e.Branch, e.HeadOid, e.Base, e.Action, e.Strategy, e.At,
		e.MergedInto, e.MergedKind); err != nil {
		log.Printf("留痕写库失败（只丢这条摘要）: %v", err)
		return
	}
	_, _ = s.db.Exec(`DELETE FROM project_traces WHERE repo=? AND id NOT IN
		(SELECT id FROM project_traces WHERE repo=? ORDER BY at DESC, rowid DESC LIMIT ?)`,
		e.Repo, e.Repo, traceKeep)
}

// traceKeep 每个仓库保留的留痕条数。UI 一次读 50，留 1000 条足够往回翻，
// 也远到不了让「读最近 50 条」变慢的量级。
const traceKeep = 1000

// traceFile 是降级模式（开不了库）下的老路：JSONL 追加，超 5MB 轮转一代。
func (s *Store) traceFile(e TraceEntry) {
	p := s.tracePath()
	if p == "" {
		return
	}
	if st, err := os.Stat(p); err == nil && st.Size() > 5<<20 {
		_ = os.Rename(p, p+".1")
	}
	b, err := json.Marshal(e)
	if err != nil {
		return
	}
	f, err := os.OpenFile(p, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = f.Write(append(b, '\n'))
}

// ReadTrace 读某仓库最近的留痕（新在前，最多 limit 条）。
func (s *Store) ReadTrace(repoDir string, limit int) []TraceEntry {
	if limit <= 0 {
		return nil
	}
	if s.db.OK() {
		return s.readTraceDB(repoDir, limit)
	}
	return s.readTraceFile(repoDir, limit)
}

// readTraceDB 按 (repo, at DESC) 走索引取最近几条。rowid 兜底定序：同一秒里
// 连着落的几条（一次清理会一口气写好几条）光看 at 分不出先后。
func (s *Store) readTraceDB(repoDir string, limit int) []TraceEntry {
	rows, err := s.db.Query(`SELECT id, repo, IFNULL(branch,''), IFNULL(head_oid,''),
		IFNULL(base,''), IFNULL(action,''), IFNULL(strategy,''), at,
		IFNULL(merged_into,''), IFNULL(merged_kind,'')
		FROM project_traces WHERE repo=? ORDER BY at DESC, rowid DESC LIMIT ?`, repoDir, limit)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []TraceEntry
	for rows.Next() {
		var e TraceEntry
		if rows.Scan(&e.ID, &e.Repo, &e.Branch, &e.HeadOid, &e.Base, &e.Action,
			&e.Strategy, &e.At, &e.MergedInto, &e.MergedKind) != nil {
			continue
		}
		out = append(out, e)
	}
	return out
}

// readTraceFile 是降级模式下的老路：**从文件尾部往回读**。留痕是只追加的 JSONL，
// 要的永远是最新那几条，而文件会长到 5MB 才轮转一代。整个读进来解析（最多 10MB）
// 只为挑出 50 条，代价按打开次数付。按块回读，凑够就停。
func (s *Store) readTraceFile(repoDir string, limit int) []TraceEntry {
	p := s.tracePath()
	if p == "" || limit <= 0 {
		return nil
	}
	var out []TraceEntry
	// 先读当前这代，不够再往上一代找
	for _, f := range []string{p, p + ".1"} {
		if len(out) >= limit {
			break
		}
		out = append(out, tailTrace(f, repoDir, limit-len(out))...)
	}
	return out
}

// traceChunk 每次回读的块大小。留痕一行 200 字节上下，64KB 够覆盖几百条，
// 绝大多数情况一块就够。
const traceChunk = 64 << 10

// tailTrace 从文件末尾往回扫，收集属于 repoDir 的留痕（新在前），最多 want 条。
func tailTrace(path, repoDir string, want int) []TraceEntry {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil
	}
	var (
		out  []TraceEntry
		pos  = st.Size()
		rest []byte // 上一块开头那半行，拼到下一块（往回读）的末尾
	)
	for pos > 0 && len(out) < want {
		n := int64(traceChunk)
		if n > pos {
			n = pos
		}
		pos -= n
		buf := make([]byte, n)
		if _, err := f.ReadAt(buf, pos); err != nil {
			return out
		}
		buf = append(buf, rest...)
		lines := bytes.Split(buf, []byte("\n"))
		// 第一段可能是半行（除非已读到文件开头），留给下一块拼
		if pos > 0 {
			rest, lines = lines[0], lines[1:]
		} else {
			rest = nil
		}
		for i := len(lines) - 1; i >= 0 && len(out) < want; i-- {
			line := bytes.TrimSpace(lines[i])
			if len(line) == 0 {
				continue
			}
			var e TraceEntry
			if json.Unmarshal(line, &e) == nil && e.Repo == repoDir {
				out = append(out, e)
			}
		}
	}
	return out
}

// SetDir 把条目挪到新目录（仓库子目录归位到根、用户 mv 了项目目录）。**id 不变**，
// 所以偏好/置顶/留痕指向都跟着走。新目录已被另一个条目占用才合并：用户意志按或
// 语义保留，被合并掉的 id 记成别名，老链接照样能打开。返回现行 id。
func (s *Store) SetDir(key, newDir string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := s.resolve(key)
	if k == "" || newDir == "" {
		return ""
	}
	e := s.repos[k]
	if e.Dir == newDir {
		return k
	}
	if dstKey, exists := s.byDir[newDir]; exists && dstKey != k {
		mergeInto(s.repos[dstKey], e)
		delete(s.byDir, e.Dir)
		delete(s.repos, k)
		s.aliases[k] = dstKey
		for alias, to := range s.aliases {
			if to == k {
				s.aliases[alias] = dstKey
			}
		}
		s.save()
		return dstKey
	}
	delete(s.byDir, e.Dir)
	e.Dir = newDir
	s.byDir[newDir] = k
	s.save()
	return k
}
