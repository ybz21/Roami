package swarm

import (
	"database/sql"
	"fmt"
	metadb "github.com/ybz21/Roami/internal/storage"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// MemberSpec is the full row spec for a swarm member.
type MemberSpec struct {
	Name    string
	Type    string // task | agent
	Task    string
	Workdir string
	Model   string
	Perm    string
	Kind    string // claude | codex
	Role    string // leader | member
	Subrole string // 细分角色 key: pm|architect|frontend|backend|qa|… (自定义原样)
	Duty    string // 长期职责（负责哪一块/产出标准）
}

// SwarmRow is one swarm in the registry listing.
type SwarmRow struct {
	ID, Name, Goal, Status, Supervisor, Created, Dir string
}

// NewSwarm inserts a planning swarm and initializes its db. Returns the id.
// dir 是蜂群的工作目录(绝对路径, 可空)——Web 项目视图按它把蜂群归到项目，
// 不能只靠成员会话名(ls --json 会把蜂群会话过滤掉，见 issue #125)。
func (s *Store) NewSwarm(name, goal, dir string) (string, error) {
	if err := s.MetaInit(); err != nil {
		return "", err
	}
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return "", err
	}
	defer db.Close()
	id := s.NewID()
	_, err = db.Exec(`INSERT INTO swarms(id,name,goal,status,supervisor,created,dir)
		VALUES(?,?,?,'planning','',?,?)`, id, name, goal, s.opt.Now().Format("2006-01-02 15:04:05"), dir)
	if err != nil {
		return "", err
	}
	return id, nil
}

// ListSwarms returns all swarms ordered by creation.
func (s *Store) ListSwarms() ([]SwarmRow, error) {
	if err := s.MetaInit(); err != nil {
		return nil, err
	}
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return nil, err
	}
	defer db.Close()
	rows, err := db.Query(`SELECT id,name,IFNULL(goal,''),IFNULL(status,''),IFNULL(supervisor,''),IFNULL(created,''),IFNULL(dir,'') FROM swarms ORDER BY created`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []SwarmRow
	for rows.Next() {
		var r SwarmRow
		if err := rows.Scan(&r.ID, &r.Name, &r.Goal, &r.Status, &r.Supervisor, &r.Created, &r.Dir); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// HasLeader reports whether a leader/master member already exists.
func (s *Store) HasLeader(swarm string) bool {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return false
	}
	defer db.Close()
	var n int
	_ = db.QueryRow(`SELECT COUNT(*) FROM swarm_members WHERE swarm_id=? AND role IN ('leader','master')`, sid).Scan(&n)
	return n > 0
}

// DepGet/DepSet read/write a member's dependency list.
func (s *Store) DepGet(swarm, member string) string {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return ""
	}
	defer db.Close()
	var deps string
	_ = db.QueryRow(`SELECT IFNULL(deps,'') FROM swarm_members WHERE swarm_id=? AND name=?`, sid, member).Scan(&deps)
	return deps
}

func (s *Store) DepSet(swarm, member, deps string) error {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.Exec(`INSERT INTO swarm_members(swarm_id,name,deps) VALUES(?,?,?)
		ON CONFLICT(swarm_id,name) DO UPDATE SET deps=excluded.deps`, sid, member, deps)
	return err
}

// MarkMemberDone / IsMemberMarkedDone / DoneList back the done column.
func (s *Store) MarkMemberDone(swarm, member string) error {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.Exec(`INSERT INTO swarm_members(swarm_id,name,done) VALUES(?,?,1)
		ON CONFLICT(swarm_id,name) DO UPDATE SET done=1`, sid, member)
	return err
}

func (s *Store) isMarkedDone(swarm, member string) bool {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return false
	}
	defer db.Close()
	var done int
	_ = db.QueryRow(`SELECT IFNULL(done,0) FROM swarm_members WHERE swarm_id=? AND name=?`, sid, member).Scan(&done)
	return done == 1
}

// AddMemberRow upserts a launched (non-pending) member row.
func (s *Store) AddMemberRow(swarm string, m MemberSpec) error {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.Exec(`INSERT INTO swarm_members(swarm_id,name,type,task,workdir,model,perm,kind,role,subrole,duty,pending,done)
		VALUES(?,?,?,?,?,?,?,?,?,?,?,0,0)
		ON CONFLICT(swarm_id,name) DO UPDATE SET type=excluded.type,task=excluded.task,
			workdir=excluded.workdir,model=excluded.model,perm=excluded.perm,
			kind=excluded.kind,role=excluded.role,subrole=excluded.subrole,duty=excluded.duty,pending=0`,
		sid, m.Name, m.Type, m.Task, m.Workdir, m.Model, m.Perm, m.Kind, m.Role, SubroleNorm(m.Subrole), m.Duty)
	return err
}

// SetPending upserts a member as pending (awaiting deps), storing its spec.
func (s *Store) SetPending(swarm string, m MemberSpec) error {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.Exec(`INSERT INTO swarm_members(swarm_id,name,type,task,workdir,model,perm,kind,role,subrole,duty,pending)
		VALUES(?,?,?,?,?,?,?,?,?,?,?,1)
		ON CONFLICT(swarm_id,name) DO UPDATE SET type=excluded.type,task=excluded.task,
			workdir=excluded.workdir,model=excluded.model,perm=excluded.perm,
			kind=excluded.kind,role=excluded.role,subrole=excluded.subrole,duty=excluded.duty,pending=1`,
		sid, m.Name, m.Type, m.Task, m.Workdir, m.Model, m.Perm, m.Kind, RoleNorm(m.Role), SubroleNorm(m.Subrole), m.Duty)
	return err
}

func (s *Store) clearPending(swarm, member string) error {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.Exec(`UPDATE swarm_members SET pending=0 WHERE swarm_id=? AND name=?`, sid, member)
	return err
}

// PendingList returns the names of members awaiting dependencies.
func (s *Store) PendingList(swarm string) []string {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return nil
	}
	defer db.Close()
	rows, err := db.Query(`SELECT name FROM swarm_members WHERE swarm_id=? AND pending=1 ORDER BY name`, sid)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var n string
		if rows.Scan(&n) == nil {
			out = append(out, n)
		}
	}
	return out
}

// pendingSpec loads the stored spec for a pending member.
func (s *Store) pendingSpec(swarm, member string) (MemberSpec, error) {
	db, sid, err := s.scope(swarm)
	if err != nil {
		return MemberSpec{}, err
	}
	defer db.Close()
	m := MemberSpec{Name: member}
	err = db.QueryRow(`SELECT IFNULL(type,'agent'),IFNULL(task,''),IFNULL(workdir,''),
		IFNULL(model,''),IFNULL(perm,''),IFNULL(kind,'claude'),IFNULL(role,'member'),
		IFNULL(subrole,''),IFNULL(duty,'')
		FROM swarm_members WHERE swarm_id=? AND name=?`, sid, member).
		Scan(&m.Type, &m.Task, &m.Workdir, &m.Model, &m.Perm, &m.Kind, &m.Role, &m.Subrole, &m.Duty)
	return m, err
}

// MemberDone reports completion for dependency gating: explicit done mark,
// dead pane, or a vanished session that has a log (mirrors _swarm_member_done).
func (s *Store) MemberDone(swarm, member string) bool {
	if s.isMarkedDone(swarm, member) {
		return true
	}
	sess := s.MemberSession(swarm, member)
	if tmuxHasSession(s.opt.TmuxBin, sess) {
		dead := strings.TrimSpace(runTmux(s.opt.TmuxBin, "display-message", "-t", "="+sess+":", "-p", "#{pane_dead}"))
		return dead == "1"
	}
	_, err := os.Stat(filepath.Join(s.opt.DataDir, "logs", sess+".log"))
	return err == nil
}

// DepsSatisfied reports whether all of a member's deps are complete.
func (s *Store) DepsSatisfied(swarm, member string) bool {
	deps := s.DepGet(swarm, member)
	if strings.TrimSpace(deps) == "" {
		return true
	}
	for _, d := range strings.Split(deps, ",") {
		d = strings.TrimSpace(d)
		if d == "" {
			continue
		}
		if !s.MemberDone(swarm, d) {
			return false
		}
	}
	return true
}

// SpawnFunc launches a member session; supplied by the command layer so the
// core stays free of tmux-orchestration/agent-launch code.
type SpawnFunc func(swarm string, m MemberSpec) (bool, error)

// Activate unlocks pending members whose deps are satisfied, cascading until no
// further members launch (mirrors _swarm_activate). `only` limits to one member
// (no cascade); `force` ignores deps. Returns the number launched.
func (s *Store) Activate(swarm string, only string, force bool, spawn SpawnFunc) (int, error) {
	launched := 0
	for changed := true; changed; {
		changed = false
		for _, m := range s.PendingList(swarm) {
			if only != "" && m != only {
				continue
			}
			if !force && !s.DepsSatisfied(swarm, m) {
				continue
			}
			spec, err := s.pendingSpec(swarm, m)
			if err != nil {
				continue
			}
			ok, err := spawn(swarm, spec)
			if err != nil {
				return launched, err
			}
			if ok {
				if err := s.clearPending(swarm, m); err != nil {
					return launched, err
				}
				launched++
				changed = true
			}
		}
		if only != "" {
			break
		}
	}
	return launched, nil
}

// Migrate imports legacy file-based swarm metadata under DataDir/swarms/<name>/
// into meta.db and seeds member rows from .group files (mirrors _swarm_migrate).
// Returns the number of swarms touched.
func (s *Store) Migrate(groupSessions func(group string) []string, taskType, taskDesc func(sess string) string) (int, error) {
	if err := s.MetaInit(); err != nil {
		return 0, err
	}
	legacyRoot := filepath.Join(s.opt.DataDir, "swarms")
	entries, _ := os.ReadDir(legacyRoot)
	n := 0
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		name := e.Name()
		dir := filepath.Join(legacyRoot, name)
		created := readFirst(filepath.Join(dir, "created.txt"))
		goal := readFirst(filepath.Join(dir, "goal.txt"))
		status := readFirst(filepath.Join(dir, "status.txt"))
		supervisor := readFirst(filepath.Join(dir, "supervisor.txt"))
		if err := s.migrateOne(name, created, goal, status, supervisor); err != nil {
			return n, err
		}
		n++
	}
	// Seed member rows from .group files for every registered swarm.
	rows, err := s.ListSwarms()
	if err != nil {
		return n, err
	}
	for _, r := range rows {
		s.migrateMembers(r.Name, groupSessions, taskType, taskDesc)
	}
	return n, nil
}

func (s *Store) migrateOne(name, created, goal, status, supervisor string) error {
	if s.ResolveID(name) != "" {
		return nil // already indexed
	}
	if created == "" {
		created = s.opt.Now().Format("2006-01-02 15:04:05")
	}
	if status == "" {
		status = "planning"
	}
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return err
	}
	defer db.Close()
	_, err = db.Exec(`INSERT INTO swarms(id,name,goal,status,supervisor,created) VALUES(?,?,?,?,?,?)`,
		s.NewID(), name, goal, status, supervisor, created)
	return err
}

// MigrateSessionNames 会话改名成 id 后，把蜂群台账里记的会话名一起换掉：
// swarms.supervisor（指挥会话）与各群 members.session（成员会话）。
// mapping 是 {老会话名: 新会话名}，由 runtime.MigrateSessionsToID 产出。
func (s *Store) MigrateSessionNames(mapping map[string]string) {
	if len(mapping) == 0 {
		return
	}
	swarms, err := s.ListSwarms()
	if err != nil {
		return
	}
	for _, sw := range swarms {
		if neu, ok := mapping[sw.Supervisor]; ok {
			_ = s.MetaSet(sw.Name, "supervisor", neu)
		}
		db, sid, err := s.scope(sw.Name)
		if err != nil {
			continue
		}
		// 成员会话名以前是 `<群>-<成员>`（没落过 session 列），改名后要按新名字补上
		rows, _ := db.Query(`SELECT name, IFNULL(session,'') FROM swarm_members WHERE swarm_id=?`, sid)
		type pair struct{ member, sess string }
		var todo []pair
		if rows != nil {
			for rows.Next() {
				var m, sess string
				if rows.Scan(&m, &sess) == nil {
					if sess == "" {
						sess = MemberLabel(sw.Name, m)
					}
					if neu, ok := mapping[sess]; ok {
						todo = append(todo, pair{m, neu})
					}
				}
			}
			rows.Close()
		}
		for _, p := range todo {
			_, _ = db.Exec(`UPDATE swarm_members SET session=? WHERE swarm_id=? AND name=?`, p.sess, sid, p.member)
		}
		db.Close()
	}
}

func (s *Store) migrateMembers(name string, groupSessions func(string) []string, taskType, taskDesc func(string) string) {
	db, sid, err := s.scope(name)
	if err != nil {
		return
	}
	defer db.Close()
	supervisor := s.MetaGet(name, "supervisor")
	rt := runtime.Runtime{TmuxBin: s.opt.TmuxBin}
	for _, sess := range groupSessions(name) {
		// 台账存的是会话名(= id)，成员名要从展示名 `<群>-<成员>` 反推；
		// 老 bash 蜂群的台账里存的本来就是语义名，取不到展示名时原样用。
		label := sess
		if row := rt.SessionRow(sess); row.Name != "" {
			label = row.DisplayLabel()
		}
		member := strings.TrimPrefix(label, name+"-")
		role := "member"
		if supervisor != "" && sess == supervisor {
			role = "leader"
		}
		_, _ = db.Exec(`INSERT INTO swarm_members(swarm_id,name,type,task,role,session,pending,done) VALUES(?,?,?,?,?,?,0,0)
			ON CONFLICT(swarm_id,name) DO UPDATE SET
				type=COALESCE(NULLIF(swarm_members.type,''), excluded.type),
				task=COALESCE(NULLIF(swarm_members.task,''), excluded.task),
				session=COALESCE(NULLIF(swarm_members.session,''), excluded.session)`,
			sid, member, taskType(sess), taskDesc(sess), role, sess)
	}
}

func readFirst(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(b), "\n") {
		return strings.TrimSpace(line)
	}
	return ""
}

// ReadQuery runs a read-only query against a swarm's db and returns the column
// names and string rows (backs `swarm sql`).
func (s *Store) ReadQuery(swarm, query string) ([]string, [][]string, error) {
	id := s.ResolveID(swarm)
	if id == "" {
		return nil, nil, fmt.Errorf("swarm not found: %s", swarm)
	}
	// 专用只读连接，不走共享池：下面要建临时视图，而临时对象是**按连接**的，
	// 落在池里会随机漏给别的调用方。这条命令是人手敲的，不在热路径上，多开一条不心疼。
	db, err := sql.Open("sqlite", "file:"+s.metaPath()+"?_pragma=busy_timeout(5000)&mode=ro")
	if err != nil {
		return nil, nil, err
	}
	db.SetMaxOpenConns(1)
	defer db.Close()

	// members / cards 现在住在主库、靠 swarm_id 分群。用按群限定的临时视图把老名字
	// 还回去：`SELECT ... FROM members` 这类既有查询照常能用，而且看不到别的群。
	// posts 仍在每群自己的库里，attach 进来。
	for _, q := range []string{
		`CREATE TEMP VIEW members AS SELECT * FROM swarm_members WHERE swarm_id=` + sqlLiteral(id),
		`CREATE TEMP VIEW cards AS SELECT * FROM swarm_cards WHERE swarm_id=` + sqlLiteral(id),
		`ATTACH DATABASE ` + sqlLiteral(s.swarmDBPath(id)) + ` AS perswarm`,
	} {
		if _, err := db.Exec(q); err != nil && !strings.Contains(err.Error(), "unable to open") {
			return nil, nil, err
		}
	}
	// posts 视图单独建：库不存在时（从没发过帖）上面的 ATTACH 会失败，那就跳过。
	_, _ = db.Exec(`CREATE TEMP VIEW posts AS SELECT * FROM perswarm.posts`)

	rows, err := db.Query(query)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	cols, err := rows.Columns()
	if err != nil {
		return nil, nil, err
	}
	var out [][]string
	for rows.Next() {
		raw := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range raw {
			ptrs[i] = &raw[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, nil, err
		}
		rec := make([]string, len(cols))
		for i, v := range raw {
			switch t := v.(type) {
			case nil:
				rec[i] = ""
			case []byte:
				rec[i] = string(t)
			default:
				rec[i] = fmt.Sprintf("%v", t)
			}
		}
		out = append(out, rec)
	}
	return cols, out, rows.Err()
}

// PendingCount returns how many members await dependencies.
func (s *Store) PendingCount(swarm string) int { return len(s.PendingList(swarm)) }

// Remove deletes a swarm's registry row and on-disk data.
func (s *Store) Remove(swarm string) error {
	id := s.ResolveID(swarm)
	if id == "" {
		return fmt.Errorf("swarm not found: %s", swarm)
	}
	db, err := openMeta(s.opt.HomeDir, s.opt.DataDir)
	if err != nil {
		return err
	}
	_, err = db.Exec(`DELETE FROM swarms WHERE id=?`, id)
	db.Close()
	if err != nil {
		return err
	}
	paths, e := metadb.ResolvePaths(s.opt.HomeDir, s.opt.DataDir)
	if e != nil {
		return e
	}
	if e = paths.MarkArchived("swarm:" + id); e != nil {
		return e
	}
	return os.RemoveAll(s.swarmHome(id))
}

// sqlLiteral 把字符串包成 SQL 字面量（临时视图的定义不能用占位符）。
// 输入是我们自己解析出来的蜂群 id 与库路径，不是用户串；转义单引号只为稳妥。
func sqlLiteral(v string) string { return "'" + strings.ReplaceAll(v, "'", "''") + "'" }
