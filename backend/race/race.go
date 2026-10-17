// Package race 是竞赛（设计 07 §3 W5/W6）的数据层：一场竞赛 = 一个 prompt × N 选手，
// 每人一个隔离 worktree + 会话。
//
// 它从 package api 搬出来，是为了让**编译器**守住封装：此前 handler 直接持
// s.mu、读写 s.races 切片，连 api/project.go 都跨文件遍历裸字段统计每个目录有几场
// 在跑——换存储时这种耦合会一路炸开，而靠 review 纪律是拦不住的。搬包之后
// 那些字段跨包不可见，想碰只能走下面的方法。
//
// 变更原语只有 Update 一个：读→改→写在同一把锁里做完。crown 那套状态机以前是
// 「拿到 *Race 指针 → 解锁 → 在长耗时的 git 操作之间反复读写 race.CrownDone」，
// 并发两个 crown 请求就是数据竞争；现在一律走值语义的快照。
package race

import (
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/ybz21/Roami/internal/id"
	"github.com/ybz21/Roami/internal/metadb"
)

type Contestant struct {
	// Session 会话名(= 会话 id)：打开终端/发消息的 handle。
	// Label 展示名 `<竞赛>-<字母>`：给人看的。
	Session string `json:"session"`
	Label   string `json:"label,omitempty"`
	// SessionID tmux #{session_id}：会话被改名后仍能找回同一个会话（名字只是 handle）。
	SessionID string `json:"sessionId,omitempty"`
	Agent     string `json:"agent"` // claude | codex
	Branch    string `json:"branch"`
	Path      string `json:"path"`
	Status    string `json:"status"` // running | failed
	Error     string `json:"error,omitempty"`
}

type Race struct {
	ID string `json:"id"`
	// LegacyID 老格式 id（race-<纳秒>）：启动时统一重写成可读 id，这条留着让
	// 已经打开的页面/链接仍能按老 id 找到本场竞赛。
	LegacyID    string       `json:"legacyId,omitempty"`
	Name        string       `json:"name"`
	Dir         string       `json:"dir"` // 仓库目录
	Base        string       `json:"base"`
	Prompt      string       `json:"prompt"`
	CreatedAt   string       `json:"createdAt"`
	Status      string       `json:"status"` // running | crowned | cleaned
	Winner      string       `json:"winner,omitempty"`
	CrownDone   []string     `json:"crownDone,omitempty"` // crown 状态机已完成阶段（失败可续跑）
	Contestants []Contestant `json:"contestants"`
}

type Store struct {
	db    *metadb.DB // 直连时的真相源；nil/降级则写 races.json
	mu    sync.Mutex
	path  string
	races []*Race
}

// NewStore 建竞赛台账。db 直连可用时以库为准，否则退回 races.json。
// 同 project.Store：只换 load/save 两端，业务方法（crown 状态机等）一行没动。
func NewStore(dataDir string, db *metadb.DB) *Store {
	s := &Store{db: db}
	if db.OK() {
		s.loadDB()
		s.normalizeIDs()
		return s
	}
	if dataDir != "" {
		s.path = filepath.Join(dataDir, "races.json")
		if b, err := os.ReadFile(s.path); err == nil {
			_ = json.Unmarshal(b, &s.races)
		}
		s.normalizeIDs()
	}
	return s
}

// save 持久化全量列表（调用方须持锁）。
func (s *Store) save() {
	if s.db.OK() {
		s.saveDB()
		return
	}
	if s.path == "" {
		return
	}
	b, err := json.MarshalIndent(s.races, "", "  ")
	if err != nil {
		return
	}
	tmp := s.path + ".tmp"
	if os.WriteFile(tmp, b, 0o600) == nil {
		_ = os.Rename(tmp, s.path)
	}
}

// loadDB / saveDB 是 races 表这一端。contestants / crownDone 存 JSON 文本列：
// 选手永远整体读写，唯一的聚合查询（每个 dir 有几场在跑）压根不看选手，
// 拆子表只会多一层 join 而换不来任何东西。
func (s *Store) loadDB() {
	rows, err := s.db.Query(`SELECT id, IFNULL(legacy_id,''), IFNULL(name,''), IFNULL(dir,''),
		IFNULL(base,''), IFNULL(prompt,''), IFNULL(created_at,''), IFNULL(status,'running'),
		IFNULL(winner,''), IFNULL(crown_done,''), IFNULL(contestants,'') FROM races`)
	if err != nil {
		return
	}
	defer rows.Close()
	for rows.Next() {
		var r Race
		var done, cts string
		if rows.Scan(&r.ID, &r.LegacyID, &r.Name, &r.Dir, &r.Base, &r.Prompt,
			&r.CreatedAt, &r.Status, &r.Winner, &done, &cts) != nil {
			continue
		}
		if done != "" {
			_ = json.Unmarshal([]byte(done), &r.CrownDone)
		}
		if cts != "" {
			_ = json.Unmarshal([]byte(cts), &r.Contestants)
		}
		cp := r
		s.races = append(s.races, &cp)
	}
}

func (s *Store) saveDB() {
	err := s.db.Tx(func(tx *sql.Tx) error {
		keep := make([]any, 0, len(s.races))
		for _, r := range s.races {
			done, _ := json.Marshal(r.CrownDone)
			cts, _ := json.Marshal(r.Contestants)
			if _, err := tx.Exec(`INSERT INTO races
				(id,legacy_id,name,dir,base,prompt,created_at,status,winner,crown_done,contestants)
				VALUES(?,?,?,?,?,?,?,?,?,?,?)
				ON CONFLICT(id) DO UPDATE SET legacy_id=excluded.legacy_id, name=excluded.name,
					dir=excluded.dir, base=excluded.base, prompt=excluded.prompt,
					created_at=excluded.created_at, status=excluded.status, winner=excluded.winner,
					crown_done=excluded.crown_done, contestants=excluded.contestants`,
				r.ID, r.LegacyID, r.Name, r.Dir, r.Base, r.Prompt, r.CreatedAt,
				r.Status, r.Winner, string(done), string(cts)); err != nil {
				return err
			}
			keep = append(keep, r.ID)
		}
		if len(keep) == 0 {
			_, err := tx.Exec(`DELETE FROM races`)
			return err
		}
		ph := strings.TrimSuffix(strings.Repeat("?,", len(keep)), ",")
		_, err := tx.Exec(`DELETE FROM races WHERE id NOT IN (`+ph+`)`, keep...)
		return err
	})
	if err != nil {
		log.Printf("竞赛台账写库失败: %v", err)
	}
}

func (s *Store) get(id string) *Race {
	for _, r := range s.races {
		if r.ID == id || (r.LegacyID != "" && r.LegacyID == id) {
			return r
		}
	}
	return nil
}

// normalizeIDs 把历史的 race-<纳秒> 统一成可读 id（YYYY-MMDD-HHMM-rand4，与蜂群/
// 项目同款），老 id 落进 legacyId 继续可解析。只在加载时跑一次。
func (s *Store) normalizeIDs() {
	changed := false
	for _, r := range s.races {
		if r.ID == "" || id.Valid(r.ID) {
			continue
		}
		r.LegacyID, r.ID = r.ID, id.New()
		changed = true
	}
	if changed {
		s.save()
	}
}

// ErrNotFound 竞赛不在台账里。
var ErrNotFound = errors.New("race: 竞赛不存在")

// ── 公开边界 ──────────────────────────────────────────────────────────
//
// 读一律返回**深拷贝**：调用方拿到就不再持锁，也不可能顺手改到台账里的那份。
// 写只有 Update 一个原语，读→改→写在同一把锁里做完。

func clone(r *Race) *Race {
	cp := *r
	cp.CrownDone = append([]string(nil), r.CrownDone...)
	cp.Contestants = append([]Contestant(nil), r.Contestants...)
	return &cp
}

// List 返回全部竞赛（深拷贝，按台账顺序）。
func (s *Store) List() []*Race {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]*Race, 0, len(s.races))
	for _, r := range s.races {
		out = append(out, clone(r))
	}
	return out
}

// Get 按 id（或老 legacyId）取一场竞赛的快照。
func (s *Store) Get(raceID string) (*Race, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r := s.get(raceID)
	if r == nil {
		return nil, false
	}
	return clone(r), true
}

// RunningByDir 统计每个仓库目录下正在跑的竞赛数。项目页要的就是这一个数字
// ——以前它跨文件遍历 s.races 的裸字段自己数。
func (s *Store) RunningByDir() map[string]int {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := map[string]int{}
	for _, r := range s.races {
		if r.Status == "running" && r.Dir != "" {
			out[filepath.Clean(r.Dir)]++
		}
	}
	return out
}

// Create 追加一场新竞赛。
func (s *Store) Create(r *Race) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.races = append(s.races, clone(r))
	s.save()
}

// Delete 删除一场竞赛，返回是否删到了。
func (s *Store) Delete(raceID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, r := range s.races {
		if r.ID == raceID || (r.LegacyID != "" && r.LegacyID == raceID) {
			s.races = append(s.races[:i], s.races[i+1:]...)
			s.save()
			return true
		}
	}
	return false
}

// Update 是**唯一**的变更原语：在锁内把 fn 应用到台账里的那一份、落盘，返回更新
// 后的快照。fn 返回错误则一个字节都不写。
//
// crown 那套跨 git 操作的长流程靠它拆成若干次短事务：绝不把锁（或指针）带进
// git 调用里——那正是此前那个数据竞争的成因。
func (s *Store) Update(raceID string, fn func(*Race) error) (*Race, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r := s.get(raceID)
	if r == nil {
		return nil, ErrNotFound
	}
	work := clone(r)
	if err := fn(work); err != nil {
		return nil, err
	}
	*r = *work
	s.save()
	return clone(r), nil
}

// SetStatus 改状态（crowned / cleaned）。
func (s *Store) SetStatus(raceID, status string) (*Race, error) {
	return s.Update(raceID, func(r *Race) error { r.Status = status; return nil })
}

// FreezeWinner 定下赢家。**换了赢家就清空已完成阶段**——重跑要从头来，否则上一轮
// 走过的合并步骤会被当成这一轮也走过了。
func (s *Store) FreezeWinner(raceID, winner string) (*Race, error) {
	return s.Update(raceID, func(r *Race) error {
		if r.Winner != winner {
			r.Winner, r.CrownDone = winner, nil
		}
		return nil
	})
}

// MarkStage 记下一个已完成的 crown 阶段（幂等），返回最新快照。失败续跑靠它。
func (s *Store) MarkStage(raceID, stage string) (*Race, error) {
	return s.Update(raceID, func(r *Race) error {
		for _, done := range r.CrownDone {
			if done == stage {
				return nil
			}
		}
		r.CrownDone = append(r.CrownDone, stage)
		return nil
	})
}

// StageDone 报告某个阶段是否已完成——判的是**快照**，不再摸台账。
func StageDone(r *Race, stage string) bool {
	if r == nil {
		return false
	}
	for _, done := range r.CrownDone {
		if done == stage {
			return true
		}
	}
	return false
}
