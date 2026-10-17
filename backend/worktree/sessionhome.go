// 会话「归属目录」钉死（session home）。
//
// 以前 session → worktree/项目 的归属全靠**实时** pane cwd 现算：会话在项目里
// 建好，用户在终端里 `cd` 去别处（翻日志、看 /tmp、去另一个仓库瞄一眼），归属
// 立刻跟着漂——项目会话数掉 0、详情页任务流空掉、甚至被别的项目抢走。可 cd 是
// 终端里的日常动作，不是「换项目」。
//
// 现在：会话创建时（Web 建会话/建 worktree 会话/竞赛/fork 都知道目录）就把归属
// 目录钉死；CLI 直建的会话则第一次被看见时钉死。之后一律只认这个 home 目录，
// pane cwd 怎么漂都不改归属。分支/worktree 状态仍按 home 目录现算，所以在 home
// 里切分支照样实时反映。
//
// 键是 **tmux 自己的 `#{session_id}`（$3）**，不是会话名：它改名不变、server 内
// 唯一，生命周期天然等于会话，于是「改名要搬家」「同名复用继承旧归属」这两类坑
// 从根上没有。名字只作快照存着，给排障和老文件认领用。
//
// 钉死关系落 <dataDir>/session-homes.json（后端重启不丢），会话消失即收敛；
// 文件丢了也只是回到「按当前 cwd 重新钉一次」，不影响任何真相源。
package worktree

import (
	"context"
	"database/sql"
	"encoding/json"
	"log"
	"os"
	"os/exec"

	"github.com/ybz21/Roami/internal/metadb"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// homeRow 一个会话的归属。Name 只是名字快照（排障 + v1 文件认领），不参与判定。
type homeRow struct {
	Home string `json:"home"`
	Name string `json:"name,omitempty"`
	// Epoch 是钉下这一行时的 tmux server 代次。名字规则（见 pin）只能在名字取得到
	// 的时候判换代；epoch 对不上就是直接证据，补住那个洞。
	Epoch string `json:"epoch,omitempty"`
}

type homeFile struct {
	V     int                `json:"v"`
	Homes map[string]homeRow `json:"homes"` // tmux session_id → 归属
}

type homeStore struct {
	mu   sync.Mutex
	path string             // 空 = 只在内存里（测试）
	db   *metadb.DB         // 直连时的真相源（session_homes 表）
	m    map[string]homeRow // session_id → 归属
	// legacy v1 文件（会话名 → 归属目录）：首次见到同名会话时认领一次，认领完丢弃。
	legacy map[string]string
	// pending 建会话时 tmux 还问不出 session_id（极少见）→ 先按名字挂着，
	// 下次 sighting 转正。绑定不丢是硬要求：钉错/钉丢都会让会话掉出项目。
	pending map[string]string
}

// newHomeStore 建归属存储。db 直连可用时以库为准；db 为 nil（或降级）时退回
// session-homes.json；dataDir 也为空则纯内存——测试靠这条路验语义，别去掉。
func newHomeStore(dataDir string, db *metadb.DB) *homeStore {
	h := &homeStore{m: map[string]homeRow{}, legacy: map[string]string{}, pending: map[string]string{}, db: db}
	if db.OK() {
		h.loadDB()
		return h
	}
	if dataDir == "" {
		return h
	}
	h.path = filepath.Join(dataDir, "session-homes.json")
	b, err := os.ReadFile(h.path)
	if err != nil {
		return h
	}
	var f homeFile
	if json.Unmarshal(b, &f) == nil && f.Homes != nil {
		h.m = f.Homes
		return h
	}
	var v1 map[string]string // v1：{会话名: 归属目录}
	if json.Unmarshal(b, &v1) == nil {
		h.legacy = v1
	}
	return h
}

// save 落盘（调用方须持锁）：tmp + rename 原子替换。写失败只丢钉死关系，下次重钉。
func (h *homeStore) save() {
	if h.db.OK() {
		h.saveDB()
		return
	}
	if h.path == "" {
		return
	}
	b, err := json.MarshalIndent(homeFile{V: 2, Homes: h.m}, "", "  ")
	if err != nil {
		return
	}
	tmp := h.path + ".tmp"
	if os.WriteFile(tmp, b, 0o644) == nil {
		_ = os.Rename(tmp, h.path)
	}
}

// loadDB / saveDB 是 session_homes 表这一端。
//
// 这张表装的是**运行时绑定**：键是 tmux `$N`，pane 一死就收敛，换代即作废。
// 台账那一半（键是持久会话 id、会话死了也要留）在 sessions.home_dir 里，由 CLI 写
// ——两边分工不同，别混为一谈。
func (h *homeStore) loadDB() {
	rows, err := h.db.Query(`SELECT tmux_id, IFNULL(name,''), home, IFNULL(epoch,'') FROM session_homes`)
	if err != nil {
		return
	}
	defer rows.Close()
	for rows.Next() {
		var id, name, home, epoch string
		if rows.Scan(&id, &name, &home, &epoch) == nil && id != "" {
			h.m[id] = homeRow{Home: home, Name: name, Epoch: epoch}
		}
	}
}

func (h *homeStore) saveDB() {
	err := h.db.Tx(func(tx *sql.Tx) error {
		keep := make([]any, 0, len(h.m))
		for id, row := range h.m {
			if _, err := tx.Exec(`INSERT INTO session_homes(tmux_id,epoch,name,home,pinned_at)
				VALUES(?,NULLIF(?,''),?,?,?)
				ON CONFLICT(tmux_id) DO UPDATE SET epoch=excluded.epoch,
					name=excluded.name, home=excluded.home`,
				id, row.Epoch, row.Name, row.Home, time.Now().Unix()); err != nil {
				return err
			}
			keep = append(keep, id)
		}
		if len(keep) == 0 {
			_, err := tx.Exec(`DELETE FROM session_homes`)
			return err
		}
		ph := strings.TrimSuffix(strings.Repeat("?,", len(keep)), ",")
		_, err := tx.Exec(`DELETE FROM session_homes WHERE tmux_id NOT IN (`+ph+`)`, keep...)
		return err
	})
	if err != nil {
		log.Printf("会话归属写库失败: %v", err)
	}
}

// pin 首次见到即钉死并返回 home；已钉死则原样返回（cwd 漂移不改归属）。
// 顺序：已有 > 建会话时的显式绑定(pending) > v1 老文件认领 > 当前 cwd。
func (h *homeStore) pin(sessID, name, cwd string) string {
	if sessID == "" {
		return ""
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	// 同一个 `$N` 上换了会话名 = tmux server 换代后把 `$N` 重新发给了**另一个**会话
	// （会话名就是持久 id，活着的时候不会变）。这种残行不能继承：不然重启后建的第一个
	// 会话会拿到上一代某个会话的归属目录，静悄悄归错项目。当作没钉过，重钉一次。
	//
	// epoch 是第二道判据，补住名字规则的洞：名字取不到（name==""）时，光看名字
	// 分不出「同一个会话」和「换代复用」，而 epoch 对不上就是直接证据。
	ep := tmuxEpoch()
	if row, ok := h.m[sessID]; ok && sameSession(row, name, ep) {
		if row.Name == "" && name != "" {
			row.Name = name
			row.Epoch = ep
			h.m[sessID] = row
			h.save()
		}
		return row.Home
	}
	home := cwd
	if d, ok := h.pending[name]; ok && d != "" {
		home = d
	} else if d, ok := h.legacy[name]; ok && d != "" {
		home = d
	}
	if home == "" {
		return ""
	}
	delete(h.pending, name)
	delete(h.legacy, name)
	h.m[sessID] = homeRow{Home: home, Name: name, Epoch: ep}
	h.save()
	return home
}

// sameSession 判断这一行还是不是同一个会话。名字能取到就按名字（会话名是持久 id，
// 活着不会变）；取不到就靠 epoch。两者都无从判断时保守认为是同一个——
// 宁可偶尔多留一次归属，也不要把活会话的归属抹掉。
func sameSession(row homeRow, name, epoch string) bool {
	if name != "" && row.Name != "" {
		return row.Name == name
	}
	if epoch != "" && row.Epoch != "" {
		return row.Epoch == epoch
	}
	return true
}

// tmuxEpoch 问 tmux 要 server pid —— 它随 server 起落而变，是「换代」的直接证据。
func tmuxEpoch() string {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, tmuxBin(), "display-message", "-p", "#{pid}").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// bind 显式绑定（创建会话时就知道它属于哪个目录）：覆盖旧值，且早于任何 pane 采样，
// 免得「建好 5s 内就 cd 走」把归属钉错。问不出 session_id 时按名字挂起，下次转正。
func (h *homeStore) bind(sessID, name, dir string) {
	if dir == "" {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if sessID == "" {
		if name == "" || h.pending[name] == dir {
			return
		}
		h.pending[name] = dir
		return
	}
	if row, ok := h.m[sessID]; ok && row.Home == dir && row.Name == name {
		return
	}
	delete(h.pending, name)
	h.m[sessID] = homeRow{Home: dir, Name: name, Epoch: tmuxEpoch()}
	h.save()
}

func (h *homeStore) get(sessID string) string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.m[sessID].Home
}

// byName 按会话名找归属（供只知道名字的调用方：fork 继承父归属、kill 清理）。
// 名字不是身份，只在 id 问不出来时兜底：命中多个同名（不可能同时存在）取任一。
func (h *homeStore) byName(name string) (string, string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for sessID, row := range h.m {
		if row.Name == name {
			return sessID, row.Home
		}
	}
	if d, ok := h.pending[name]; ok {
		return "", d
	}
	return "", h.legacy[name]
}

// reconcile 收敛残行：alive 之外的会话删除（裸 tmux kill-session 绕过 API 也能清干净）。
// alive 为空（tmux 读失败）时不动——宁可留残行，也不能把活会话的归属抹掉。
func (h *homeStore) reconcile(alive map[string]bool) {
	if len(alive) == 0 {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	changed := false
	for sessID := range h.m {
		if !alive[sessID] {
			delete(h.m, sessID)
			changed = true
		}
	}
	if changed {
		h.save()
	}
}

// dormantSQL 休眠会话：机器重启带走、点开即恢复的那批。
//
// **与 CLI 侧 sessmeta.Store.Dormant() 是同一个口径**，改一处就要改另一处
// （两个 module 读同一张 sessions 表，没法共享代码）。逐条筛选条件的理由写在
// cli/github.com/ybz21/Roami/internal/sessionstore/sessmeta.go 的 Dormant() 上，此处不再抄一遍。
const dormantSQL = `SELECT d.id, IFNULL(d.home_dir,IFNULL(d.initial_cwd,''))
	FROM sessions d
	WHERE d.status='dead' AND d.died_reason='host-restart'
	  AND IFNULL(d.tmux_epoch,'') <> ''
	  AND d.tmux_epoch = (SELECT tmux_epoch FROM sessions
	        WHERE status='dead' AND died_reason='host-restart' AND IFNULL(tmux_epoch,'') <> ''
	        ORDER BY IFNULL(died_at,created_at) DESC LIMIT 1)
	  AND IFNULL(d.home_dir,IFNULL(d.initial_cwd,'')) <> ''
	  AND NOT EXISTS (SELECT 1 FROM sessions r WHERE r.restored_from = d.id)
	ORDER BY IFNULL(d.died_at,d.created_at) DESC
	LIMIT 200`

// dormantHomes 休眠会话的归属。让它们和活会话走**同一条**归属通道，
// 于是 Annotations / SessionCwds / worktree join / 项目详情全都自动认得它们——
// 否则就会出现「概览卡里有、点进项目又没了」这种数据不一致。
func (h *homeStore) dormantHomes() []sessionHome {
	if h.db == nil {
		return nil
	}
	rows, err := h.db.Query(dormantSQL)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []sessionHome
	for rows.Next() {
		var name, home string
		if rows.Scan(&name, &home) != nil || home == "" {
			continue
		}
		// 目录没了就不算数：worktree 被清是常事，恢复不出来的不该占着归属。
		if fi, err := os.Stat(home); err != nil || !fi.IsDir() {
			continue
		}
		out = append(out, sessionHome{Name: name, Home: canonical(home), Dormant: true})
	}
	return out
}

// ── Service 外部接口 ──────────────────────────────────────

// sessionHome 一个会话的身份三元组：tmux session_id（内部键）+ 名字（对外 handle）+ 归属目录。
type sessionHome struct {
	ID   string
	Name string
	Home string
	// Dormant 这个会话只存在于台账里：机器重启带走了 tmux 那一半，点开即恢复。
	// 归属照常算（目录一直记着），但它没有 pane、没有进程。
	Dormant bool
}

// resolveSessionID 问 tmux 要某会话的 session_id（`=name` 精确匹配，避免前缀误命中）。
// 只在建会话/清理这种低频路径调一次；tmux 不在或会话没了返回空串。
func resolveSessionID(name string) string {
	if name == "" {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, tmuxBin(), "display-message", "-t", "="+name+":", "-p", "#{session_id}").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// SessionID 返回会话当前的 tmux session_id（不存在返回空串）。记录类数据（竞赛选手等）
// 存下它，之后即便会话被改名也能找回同一个会话。
func (s *Service) SessionID(name string) string { return resolveSessionID(name) }

// SessionNameByID 反查 session_id 现在的会话名（会话已死返回空串）。
func (s *Service) SessionNameByID(sessID string) string {
	if sessID == "" {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, tmuxBin(), "display-message", "-t", sessID, "-p", "#{session_name}").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// BindSessionHome 显式钉死会话归属目录（建会话的编排方调用，只知道会话名）。
func (s *Service) BindSessionHome(session, dir string) {
	if dir == "" {
		return
	}
	s.homes.bind(resolveSessionID(session), session, canonical(dir))
}

// SessionHome 返回会话钉死的归属目录（未钉死返回空串）。
func (s *Service) SessionHome(session string) string {
	if sessID := resolveSessionID(session); sessID != "" {
		if home := s.homes.get(sessID); home != "" {
			return home
		}
	}
	_, home := s.homes.byName(session)
	return home
}

// sessionHomes 返回全部活会话的归属：已钉死的照旧，没钉过的按当前 pane（活动 pane
// 优先）钉一次；顺带收敛死会话残行。这是 session 归属的唯一入口，
// Annotations / SessionCwds / worktree 会话 join / ListAll 全部走它。
func (s *Service) sessionHomes(ctx context.Context) []sessionHome {
	return append(s.livingHomes(ctx), s.homes.dormantHomes()...)
}

// livingHomes 活会话那一半（原 sessionHomes 的全部逻辑）。
func (s *Service) livingHomes(ctx context.Context) []sessionHome {
	panes := tmuxPanes(ctx)
	alive := make(map[string]bool, len(panes))
	order := make([]string, 0, len(panes))
	name := map[string]string{}
	first := map[string]string{}
	active := map[string]string{}
	for _, p := range panes {
		if p.ID == "" {
			continue
		}
		if !alive[p.ID] {
			alive[p.ID] = true
			order = append(order, p.ID)
		}
		name[p.ID] = p.Session
		if _, ok := first[p.ID]; !ok {
			first[p.ID] = p.Cwd
		}
		if p.Active {
			active[p.ID] = p.Cwd
		}
	}
	s.homes.reconcile(alive)
	out := make([]sessionHome, 0, len(order))
	for _, sessID := range order {
		cwd := active[sessID]
		if cwd == "" {
			cwd = first[sessID]
		}
		if home := s.homes.pin(sessID, name[sessID], cwd); home != "" {
			out = append(out, sessionHome{ID: sessID, Name: name[sessID], Home: home})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

// homePanes 把归属拍回 pane 列表，让既有的「按 cwd 最长前缀归属」逻辑原样复用：
// 每会话一条、Active=true（home 就是它的归属，无歧义）。
func homePanes(homes []sessionHome) []pane {
	out := make([]pane, 0, len(homes))
	for _, h := range homes {
		out = append(out, pane{ID: h.ID, Session: h.Name, Active: true, Cwd: h.Home, Dormant: h.Dormant})
	}
	return out
}
