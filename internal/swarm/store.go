package swarm

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/id"
	metadb "github.com/ybz21/Roami/internal/storage"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// Store is the swarm data layer: meta.db registry + per-swarm swarm.db.
// It replaces the sqlite3-CLI calls in lib/store.sh / lib/swarm.sh with the
// pure-Go driver and parameterized queries (no shell escaping, no injection).
type Store struct {
	opt Options
}

func NewStore(opt Options) *Store { return &Store{opt: opt.withDefaults()} }

// Options returns the resolved options backing this store.
func (s *Store) Options() Options { return s.opt }

func (s *Store) metaPath() string {
	p, _ := metadb.ResolvePaths(s.opt.HomeDir, s.opt.DataDir)
	return p.MainPath()
}
func (s *Store) swarmHome(id string) string {
	return filepath.Join(s.opt.HomeDir, "swarms", id)
}
func (s *Store) swarmDBPath(id string) string {
	p, _ := metadb.ResolvePaths(s.opt.HomeDir, s.opt.DataDir)
	return p.SwarmPath(id)
}

func isID(s string) bool { return id.Valid(s) }

// NewID generates an instance id YYYY-MMDD-HHMM-<rand4> (mirrors _id_new)。
// 格式与后端记录 id 共用同一套（见 internal/id）。
func (s *Store) NewID() string { return id.NewAt(s.opt.Now()) }

// MetaInit ensures meta.db and the swarms table exist.
func (s *Store) MetaInit() error {
	if err := os.MkdirAll(s.opt.HomeDir, 0o755); err != nil {
		return err
	}
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return err
	}
	defer db.Close()
	// 建表与补列都在 metadb 的版本链里（baseline 那一步），开库即已就位。
	return nil
}

// ResolveID maps a name-or-id to its id ("" if unknown).
func (s *Store) ResolveID(nameOrID string) string {
	if isID(nameOrID) {
		return nameOrID
	}
	if _, err := os.Stat(s.metaPath()); err != nil {
		return ""
	}
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return ""
	}
	defer db.Close()
	var id string
	_ = db.QueryRow(`SELECT id FROM swarms WHERE name=? LIMIT 1`, nameOrID).Scan(&id)
	return id
}

// Name returns the canonical swarm name for a name-or-id.
func (s *Store) Name(nameOrID string) string {
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return ""
	}
	defer db.Close()
	var name string
	_ = db.QueryRow(`SELECT name FROM swarms WHERE name=? OR id=? LIMIT 1`, nameOrID, nameOrID).Scan(&name)
	return name
}

func (s *Store) Exists(nameOrID string) bool { return s.ResolveID(nameOrID) != "" }

// MetaGet/MetaSet read/write a swarm-level column in meta.db.
func (s *Store) MetaGet(nameOrID, col string) string {
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return ""
	}
	defer db.Close()
	var v string
	// Column name cannot be a placeholder; it is constrained to a known set.
	q := fmt.Sprintf(`SELECT IFNULL(%s,'') FROM swarms WHERE name=? OR id=? LIMIT 1`, metaCol(col))
	_ = db.QueryRow(q, nameOrID, nameOrID).Scan(&v)
	return v
}

func (s *Store) MetaSet(nameOrID, col, val string) error {
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return err
	}
	defer db.Close()
	q := fmt.Sprintf(`UPDATE swarms SET %s=? WHERE name=? OR id=?`, metaCol(col))
	_, err = db.Exec(q, val, nameOrID, nameOrID)
	return err
}

// metaCol whitelists the swarm columns to keep MetaGet/Set injection-safe.
func metaCol(col string) string {
	switch col {
	case "goal", "status", "supervisor", "created", "name", "id", "dir":
		return col
	}
	return "status"
}

// openSwarmDB opens (initializing/migrating) a swarm's per-swarm db.
func (s *Store) openSwarmDB(nameOrID string) (sharedDB, error) {
	id := s.ResolveID(nameOrID)
	if id == "" {
		return sharedDB{}, fmt.Errorf("swarm not found: %s", nameOrID)
	}
	if err := os.MkdirAll(filepath.Join(s.swarmHome(id), "logs"), 0o755); err != nil {
		return sharedDB{}, err
	}
	// 建表与补列都在 swarmSteps 里，开库即已迁移——不必再 init + migrate 各跑一遍。
	p, e := metadb.ResolvePaths(s.opt.HomeDir, s.opt.DataDir)
	if e != nil {
		return sharedDB{}, e
	}
	d, e := metadb.OpenManaged(p, metadb.DatabaseDescriptor{ID: "swarm:" + id, Kind: "swarm", Path: p.SwarmPath(id), Owner: "swarm"}, swarmSteps, metadb.Options{})
	return sharedDB{d}, e
}

// scope 打开主库并解析出蜂群 id。members/cards 现在住在主库，靠 swarm_id 分群
// ——这样成员会话能和 sessions join（成员死了还得找回它的日志）。
// posts 仍留在每群自己的库里（见 swarmSteps 的说明），走 openSwarmDB。
func (s *Store) scope(nameOrID string) (sharedDB, string, error) {
	id := s.ResolveID(nameOrID)
	if id == "" {
		return sharedDB{}, "", fmt.Errorf("swarm not found: %s", nameOrID)
	}
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	return db, id, err
}

// MemberLabel 成员会话的展示名：`<群>-<成员>`。它是 @roam_name 里存的那个名字，
// 也是 `roami session send <群>-<成员>` 这类老用法能继续命中的依据。
func MemberLabel(swarm, member string) string { return swarm + "-" + member }

// MemberSession 成员的 tmux 会话名（= 会话 id）。
// 顺序：members.session 落的值 > 按展示名现查 > 退回展示名本身（迁移前的老会话
// 就是以 `<群>-<成员>` 为会话名的）。
func (s *Store) MemberSession(swarm, member string) string {
	label := MemberLabel(s.Name(swarm), member)
	if db, sid, err := s.scope(swarm); err == nil {
		var sess string
		_ = db.QueryRow(`SELECT IFNULL(session,'') FROM swarm_members WHERE swarm_id=? AND name=?`, sid, member).Scan(&sess)
		db.Close()
		if sess != "" {
			return sess
		}
	}
	return runtime.Runtime{TmuxBin: s.opt.TmuxBin}.ResolveAlive(label)
}

// SetMemberSession 记住成员会话名（拉起成员时调用）。
func (s *Store) SetMemberSession(swarm, member, sess string) error {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.Exec(`UPDATE swarm_members SET session=? WHERE swarm_id=? AND name=?`, sess, sid, member)
	return err
}

// RoleNorm normalizes role aliases (mirrors _swarm_role_norm).
func RoleNorm(role string) string {
	switch role {
	case "leader", "lead", "master":
		return "leader"
	case "member", "worker":
		return "member"
	case "":
		return ""
	default:
		return role
	}
}

// SubroleNorm normalizes a 细分角色 to a canonical registry key (see
// docs/design/蜂群成员角色模型设计.md §3). Unknown values are kept verbatim
// (trimmed) as a custom subrole — the UI/prompt fall back to generic handling.
func SubroleNorm(s string) string {
	key := strings.ToLower(strings.TrimSpace(s))
	switch key {
	case "pm", "product", "产品", "产品经理":
		return "pm"
	case "architect", "arch", "架构", "架构师":
		return "architect"
	case "frontend", "fe", "front", "前端", "前端工程师":
		return "frontend"
	case "backend", "be", "back", "后端", "后端工程师":
		return "backend"
	case "fullstack", "full", "全栈", "全栈工程师":
		return "fullstack"
	case "qa", "test", "tester", "测试", "测试工程师":
		return "qa"
	case "designer", "design", "ui-design", "设计", "设计师":
		return "designer"
	case "reviewer", "review", "审查", "代码审查":
		return "reviewer"
	case "devops", "ops", "运维":
		return "devops"
	case "docs", "doc", "writer", "文档":
		return "docs"
	case "commander", "leader", "master", "指挥", "总指挥":
		return "commander"
	default:
		return strings.TrimSpace(s) // 自定义：原样保留
	}
}
