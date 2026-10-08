// 项目(Project)读模型聚合（08 设计 §4/§5）。项目 = git 仓库：
//
//	GET   /projects            列表聚合（发现 = 读路径副作用：cwd join 命中即记入台账；
//	                           退场也在读时收敛——目录不存在，或 无 roam worktree ∧ 无会话 ∧ 未置顶）
//	PATCH /projects/:key/prefs UI 偏好（置顶/显示名/默认 agent/默认 base）
//
// 台账与偏好在 backend/project（弱数据）；git/session/race 真相源全部现有，零写入。
package api

import (
	"context"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"encoding/json"
	"fmt"

	"github.com/gin-gonic/gin"
	"ttmux-web/project"
	"ttmux-web/worktree"
)

type projectSession struct {
	// Name 会话名(= 会话 id)：打开终端的 handle；Label 展示名(@roam_name)，给人看的。
	Name         string `json:"name"`
	Label        string `json:"label,omitempty"`
	Attached     bool   `json:"attached"`
	Running      bool   `json:"running"`         // 会话里跑着交互式 agent 进程——绿点语义（设计 W2）
	Waiting      bool   `json:"waiting"`         // 屏上有等待输入的交互框——黄点（设计 W2，优先于绿）
	Agent        string `json:"agent,omitempty"` // 品牌标用。进程树扫描本就分得出，别让前端再逐会话问一遍
	Tail         string `json:"tail,omitempty"`  // 仅 Waiting 时非空：判待输入抓的那一屏的最后一行，给行动卡当摘要
	LastActivity int64  `json:"lastActivity"`
	Branch       string `json:"branch,omitempty"` // 落在 worktree 里才有
	Linked       bool   `json:"linked,omitempty"`
	// State: 空/live = 真的活着；dormant = 台账里还认得它，点开即恢复。
	State string `json:"state,omitempty"`
	// Mem 只在**逼近上限**时带出来。项目卡和详情页的信息密度已经很高，
	// 内存平时不该占位置——涨起来了才值得跳出来（看门狗的阈值同一个数）。
	Mem *sessMem `json:"mem,omitempty"`
}

type projectSummary struct {
	Key          string           `json:"key"`
	Name         string           `json:"name"` // displayName 优先，缺省目录名
	Dir          string           `json:"dir"`
	Git          bool             `json:"git"` // 是否 git 仓库——worktree/编队/活动能力只在 git 项目开启
	Pinned       bool             `json:"pinned"`
	DefaultAgent string           `json:"defaultAgent,omitempty"`
	DefaultBase  string           `json:"defaultBase,omitempty"`
	Sessions     int              `json:"sessions"`
	Attached     int              `json:"attached"`
	Worktrees    int              `json:"worktrees"`  // 非 main、非 prunable
	Unfinished   int              `json:"unfinished"` // 孤儿 roam worktree ∧ 真·未合并（合入检测排除，10 §5）
	Cleanable    int              `json:"cleanable"`  // 孤儿 roam worktree ∧ 已合入 ∧ 无未提交改动：一键清理
	Races        int              `json:"races"`      // running 状态的竞赛数
	LastActivity int64            `json:"lastActivity"`
	FirstSeen    int64            `json:"firstSeen"`
	Archived     bool             `json:"archived,omitempty"` // 干过活但此刻空着：收进「不活跃」分组
	Top          []projectSession `json:"top"`                // 活跃会话前 3（列表卡「进行中」三行）

	// Top 是**给卡片画三行用的**，被截断过，所以它算不出总数——前端拿它数 waiting/running
	// 会漏掉第 4 个以后的会话。下面这三样在截断**之前**统计，是完整的：
	Dormant int              `json:"dormant"` // 休眠会话数（重启带走、点开即恢复）
	Running int              `json:"running"` // 跑着 agent 的会话数（全量）
	Waiting int              `json:"waiting"` // 等待输入的会话数（全量）
	Needs   []projectSession `json:"needs"`   // 全部等待输入的会话——「需要你」队列要的是它，不是 Top
}

// sessListItem 兼容解析 ttmux ls --json（数值字段 CLI 可能给字符串）。
type sessListItem struct {
	Name         string          `json:"name"`
	Label        string          `json:"label"`
	Attached     json.RawMessage `json:"attached"`
	LastActivity json.RawMessage `json:"last_activity"`
	// State: live | dormant。dormant = 机器重启带走了，点开即恢复（懒恢复，见 R2 设计稿）。
	State string `json:"state,omitempty"`
	// Mem 此刻吃了多少（cgroup 读数，含子进程全部后代）。休眠会话没有进程，为 nil。
	Mem *sessMem `json:"mem,omitempty"`
	// Dir/Repo 只有 dormant 会话带：它们没有 tmux 句柄，Annotations 那条归属路走不通，
	// 只能靠台账里记下的目录。少了这一步，重启后所有会话都掉进「散会话」。
	Dir  string `json:"dir,omitempty"`
	Repo string `json:"repo,omitempty"`
}

// sessMem 会话内存画像，原样从 ttmux ls --json 透传给前端。
type sessMem struct {
	Cur   int64 `json:"cur"`
	Peak  int64 `json:"peak,omitempty"`
	Limit int64 `json:"limit,omitempty"`
}

// dormant 这个会话是不是「点开才恢复」的休眠会话。
func (s sessListItem) dormant() bool { return s.State == "dormant" }

// homeDir 休眠会话记在台账里的归属目录（活会话为空——它们走 Annotations/SessionCwds）。
func (s sessListItem) homeDir() string {
	if s.Repo != "" {
		return s.Repo
	}
	return s.Dir
}

// memWarnPercent 内存占到上限这个比例才值得在项目卡/详情页占一个位置。
// 与看门狗发预警的阈值同源——两处说的是同一件事，不该各有各的数。
const memWarnPercent = 60

// noteworthyMem 没到警示线就返回 nil：平时安静，涨起来才跳出来。
func noteworthyMem(m *sessMem) *sessMem {
	if m == nil || m.Limit <= 0 || m.Cur*100/m.Limit < memWarnPercent {
		return nil
	}
	return m
}

func rawInt(r json.RawMessage) int64 {
	s := string(r)
	if len(s) >= 2 && s[0] == '"' {
		s = s[1 : len(s)-1]
	}
	n, _ := strconv.ParseInt(s, 10, 64)
	return n
}

// 列表响应 5s TTL 缓存（与 W4 轮询同拍，压住 O(R×N) 子进程）。
var (
	projRespMu sync.Mutex
	projRespAt time.Time
	projResp   gin.H
)

// ProjectsList GET /projects
// noteArchived 判定并回写归档态，返回这个项目此刻算不算「不活跃」。
//
// 归档不是删除，也不是用户动作：它是读时收敛的判定结果——「干过活，但此刻既没有
// 会话、也没有 roam worktree」。置顶的永远算活跃（用户明说要盯着它）。
// 一旦又开了会话就自动回到活跃，不需要谁去「取消归档」。
func (a *API) noteArchived(key string, e project.Entry, roamWts, sessions int) bool {
	idle := roamWts == 0 && sessions == 0 && !e.Pinned
	switch {
	case idle && e.ArchivedAt == 0:
		a.Projects.SetArchived(key, time.Now().Unix())
	case !idle && e.ArchivedAt != 0:
		a.Projects.SetArchived(key, 0)
	}
	return idle
}

func (a *API) ProjectsList(c *gin.Context) {
	projRespMu.Lock()
	if projResp != nil && time.Since(projRespAt) < 5*time.Second {
		resp := projResp
		projRespMu.Unlock()
		c.JSON(http.StatusOK, resp)
		return
	}
	projRespMu.Unlock()

	ctx, cancel := context.WithTimeout(c.Request.Context(), 20*time.Second)
	defer cancel()

	var sessions []sessListItem
	if out, err := a.TT.Run("ls", "--json"); err == nil {
		_ = json.Unmarshal([]byte(out), &sessions)
	}
	ann := a.WT.Annotations(ctx)

	// 发现：会话归属目录(home，见 worktree/sessionhome.go)命中的仓库自动记入台账
	// （读路径副作用，无注册流程）。归属钉死在建会话时的目录，用户 cd 走不改归属。
	for _, an := range ann {
		if an.Primary != nil && an.Primary.Repo != "" {
			a.Projects.Touch(an.Primary.Repo)
		}
	}

	races := a.Races.RunningByDir() // dir → running 竞赛数

	list := []projectSummary{}
	loose := []projectSession{}
	claimed := map[string]bool{} // session → 已归入某项目

	// 两阶段归属：先 git 项目按 annotation（primary repo，最精确），
	// 再非 git 项目按 pane cwd 目录前缀认领剩余会话（08：项目不与 git 绑定）。
	type pending struct {
		key string
		e   project.Entry
		p   *projectSummary
	}
	var nonGit []pending
	var cwds map[string][]string // 懒取：有非 git 项目才拉

	sessMemOf := make(map[string]*sessMem, len(sessions))
	for _, s := range sessions {
		if s.Mem != nil {
			sessMemOf[s.Name] = s.Mem
		}
	}

	agentRunning := runningAgentSessions() // 一次进程树扫描，供绿点判活跃（设计 W2）

	addSession := func(p *projectSummary, top *[]projectSession, name, label string, attached bool, last int64, branch string, linked, dormant bool) {
		claimed[name] = true
		p.Sessions++
		ps := projectSession{Name: name, Label: label, Attached: attached, Agent: agentRunning[name], Running: agentRunning[name] != "", LastActivity: last, Linked: linked, Branch: branch}
		ps.Mem = noteworthyMem(sessMemOf[name])
		if dormant {
			// 休眠会话没有进程：绿点/待输入一律不适用，更不该去 capture-pane 一个不存在的 pane。
			ps = projectSession{Name: name, Label: label, LastActivity: last, State: "dormant"}
			p.Dormant++
		}
		if ps.Running { // 只对在跑的会话抓屏判待输入，省掉给 idle 会话的 capture-pane
			screen := sessionCapture(name, 50)
			if ps.Waiting = sessionWaiting(screen); ps.Waiting {
				ps.Tail = sessionTail(screen, 120) // 摘要只有待输入卡用得上，不待输入就不占返回体积
			}
		}
		if ps.Attached {
			p.Attached++
		}
		if ps.LastActivity > p.LastActivity {
			p.LastActivity = ps.LastActivity
		}
		*top = append(*top, ps)
	}
	finish := func(p *projectSummary, top []projectSession) {
		summarizeSessions(p, top)
		list = append(list, *p)
	}

	for key, e := range a.Projects.Entries() {
		if _, err := os.Stat(e.Dir); err != nil {
			a.Projects.Remove(key) // 退场 (a)：项目目录已不存在
			continue
		}
		p := projectSummary{
			Key: key, Dir: e.Dir, Pinned: e.Pinned, FirstSeen: e.FirstSeen,
			DefaultAgent: e.DefaultAgent, DefaultBase: e.DefaultBase,
			Races: races[filepath.Clean(e.Dir)],
		}
		p.Name = e.DisplayName
		if p.Name == "" {
			p.Name = filepath.Base(e.Dir)
		}
		wts, err := a.WT.List(ctx, e.Dir)
		if err != nil {
			if we, ok := err.(*worktree.Err); ok && we.Code == "NOT_GIT_REPO" {
				nonGit = append(nonGit, pending{key: key, e: e, p: &p}) // 非 git 项目：目录 + 会话
				continue
			}
			continue // 一时读不出（锁竞争/超时）：保留台账，本轮跳过
		}
		// 自愈：条目 dir 指向仓库子目录（历史脏数据/瞬时误判）→ 归位到仓库根。
		// id 不变，所以偏好/置顶/老链接都不动，本轮直接按新 dir 继续算。
		if repo, rerr := a.WT.ResolveRepo(ctx, e.Dir); rerr == nil && repo.Root != e.Dir {
			if now := a.Projects.SetDir(key, repo.Root); now != key {
				continue // 并进了已在册的根条目：本轮跳过，那条自己会出现
			}
			e.Dir = repo.Root
			p.Dir = repo.Root
			p.Races = races[filepath.Clean(repo.Root)]
			if e.DisplayName == "" {
				p.Name = filepath.Base(repo.Root)
			}
		}
		p.Git = true
		roamWts := 0
		for _, w := range wts {
			if w.IsMain || w.Prunable {
				continue
			}
			p.Worktrees++
			if !w.External {
				roamWts++
				if len(w.Sessions) == 0 {
					dirty := w.Dirty > 0 || w.Untracked > 0
					switch {
					case w.MergedInto != "" && !dirty:
						p.Cleanable++ // 已合入·零损失：不进「需要你」，项目页一键清（10 §5）
					case w.CommittedAhead > 0 || dirty:
						p.Unfinished++
					}
				}
			}
			if w.LastCommitAt > p.LastActivity {
				p.LastActivity = w.LastCommitAt
			}
		}
		var top []projectSession
		for _, s := range sessions {
			an := ann[s.Name]
			if an == nil || an.Primary == nil || an.Primary.Repo != e.Dir {
				continue
			}
			branch := ""
			if an.Primary.Linked {
				branch = an.Primary.Branch
			}
			addSession(&p, &top, s.Name, s.Label, rawInt(s.Attached) > 0, rawInt(s.LastActivity), branch, an.Primary.Linked, an.Dormant)
		}
		if p.Sessions > 0 {
			a.Projects.NoteSessions(key)
		}
		// 退场 (b) 只收敛「发现」通道：不存在任何 roam worktree（clean 也算存在）
		// ∧ **从来没有过会话** ∧ 未置顶。用户显式创建（origin=user）的是一等对象，
		// 永不自动退场。
		//
		// 判的是「有没有过」而不是「此刻有没有」：tmux 随机器重启清零，按当下会话数
		// 收敛的话，重启后第一次刷新就把全部发现型项目删干净——项目是台账，不该由
		// 运行时的生死决定存亡。干过活的项目留着（此刻空着只是没开会话）。
		if e.Origin != "user" && roamWts == 0 && p.Sessions == 0 && e.LastSessionAt == 0 && !e.Pinned {
			a.Projects.Remove(key)
			continue
		}
		p.Archived = a.noteArchived(key, e, roamWts, p.Sessions)
		finish(&p, top)
	}

	// 非 git 项目：按会话 home 目录前缀认领未归属会话。同一会话归**最深(最长前缀)**
	// 的非 git 项目——嵌套目录(父/子都是非 git 项目，如 /codes 与 /codes/tmp)不能按
	// map 迭代序抢占，否则父项目先跑就把子目录会话抢走，计数在父/子间随机漂移
	// （详情页各按自身 dir 认领无此去重，于是子项目外层 0、里层 1）。对齐 worktree
	// joinSessions 的「最长前缀命中」口径。
	if len(nonGit) > 0 {
		if cwds == nil {
			cwds = a.WT.SessionCwds(ctx)
		}
		tops := make([][]projectSession, len(nonGit))
		for _, s := range sessions {
			if claimed[s.Name] {
				continue
			}
			best, bestLen := -1, -1
			for i, ng := range nonGit {
				for _, c := range cwds[s.Name] {
					if (c == ng.e.Dir || strings.HasPrefix(c, ng.e.Dir+string(filepath.Separator))) && len(ng.e.Dir) > bestLen {
						best, bestLen = i, len(ng.e.Dir)
					}
				}
			}
			if best >= 0 {
				ng := nonGit[best]
				addSession(ng.p, &tops[best], s.Name, s.Label, rawInt(s.Attached) > 0, rawInt(s.LastActivity), "", false, ann[s.Name] != nil && ann[s.Name].Dormant)
			}
		}
		for i, ng := range nonGit {
			finish(ng.p, tops[i])
		}
	}

	for _, s := range sessions {
		if !claimed[s.Name] {
			ls := projectSession{Name: s.Name, Label: s.Label, Attached: rawInt(s.Attached) > 0, Agent: agentRunning[s.Name], Running: agentRunning[s.Name] != "", LastActivity: rawInt(s.LastActivity), Mem: noteworthyMem(s.Mem)}
			if s.dormant() {
				// 休眠会话不跑进程，绿点/待输入一律不适用，也不该去 capture-pane。
				ls = projectSession{Name: s.Name, Label: s.Label, LastActivity: rawInt(s.LastActivity), State: "dormant"}
			}
			if ls.Running {
				screen := sessionCapture(s.Name, 50)
				if ls.Waiting = sessionWaiting(screen); ls.Waiting {
					ls.Tail = sessionTail(screen, 120)
				}
			}
			loose = append(loose, ls)
		}
	}
	// 散会话同样稳定排序（按名称）——活动时间只展示，不参与排序防跳变
	sort.Slice(loose, func(i, j int) bool { return loose[i].Name < loose[j].Name })

	// 服务端给稳定的缺省序：置顶 > 名称；创建时间/最近活跃等排序模式由前端按
	// firstSeen/lastActivity 字段自行切换（用户可选，v0.3）。
	sort.Slice(list, func(i, j int) bool {
		if list[i].Pinned != list[j].Pinned {
			return list[i].Pinned
		}
		return list[i].Name < list[j].Name
	})

	resp := gin.H{"data": gin.H{"projects": list, "loose": loose}}
	projRespMu.Lock()
	projResp, projRespAt = resp, time.Now()
	projRespMu.Unlock()
	c.JSON(http.StatusOK, resp)
}

// ProjectCreate POST /projects {dir, displayName?}
// 显式创建项目对象（origin=user，永不自动退场）。项目 = 任意目录，**不与 git 绑定**：
// 是 git 仓库则经 ResolveRepo 归位主仓库根（worktree 里建也归位）并开启 worktree/
// 编队/活动能力；非 git 目录照样成为项目（目录 + 会话）。
func (a *API) ProjectCreate(c *gin.Context) {
	var b struct {
		Dir         string `json:"dir"`
		DisplayName string `json:"displayName"`
		// CloneURL 填了就先把它克隆到 Dir，再按 git 项目登记。
		// 空 = 老行为（目录已存在就用它，不存在就新建一个空目录）。
		CloneURL string `json:"cloneUrl"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Dir) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	dir := strings.TrimSpace(b.Dir)
	if strings.HasPrefix(dir, "~/") || dir == "~" {
		if home, err := os.UserHomeDir(); err == nil {
			dir = filepath.Join(home, strings.TrimPrefix(strings.TrimPrefix(dir, "~"), "/"))
		}
	}
	if !filepath.IsAbs(dir) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_DIR", "message": "absolute path required"}})
		return
	}
	// 克隆要先做，做完那个目录才是个 git 仓库，下面的 ResolveRepo 才认得。
	if u := strings.TrimSpace(b.CloneURL); u != "" {
		if err := cloneInto(c.Request.Context(), u, dir); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "CLONE_FAILED", "message": err.Error()}})
			return
		}
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 10*time.Second)
	defer cancel()
	git := true
	if repo, err := a.WT.ResolveRepo(ctx, dir); err == nil {
		dir = repo.Root
	} else if we, ok := err.(*worktree.Err); !ok || we.Code != "NOT_GIT_REPO" {
		// 瞬时错误（锁竞争/超时）不能当「非 git」处理——否则 git 子目录会被
		// 存成独立项目（dir 未归位仓库根）。老实报错让用户重试。
		wtErr(c, err)
		return
	} else {
		// 非 git：目录不存在则创建（新建项目 = 也可以新建文件夹）；canonical 化对齐 cwd join 口径
		if st, serr := os.Stat(dir); serr != nil {
			if mkerr := os.MkdirAll(dir, 0o755); mkerr != nil {
				c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_DIR", "message": mkerr.Error()}})
				return
			}
		} else if !st.IsDir() {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_DIR", "message": "path exists but is not a directory"}})
			return
		}
		if r, e := filepath.EvalSymlinks(dir); e == nil {
			dir = r
		}
		dir = filepath.Clean(dir)
		git = false
	}
	key, created := a.Projects.Add(dir, strings.TrimSpace(b.DisplayName))
	projRespMu.Lock()
	projResp = nil
	projRespMu.Unlock()
	// 没新建 = 目录归位到了一个已在册的仓库（多半是它的某个 worktree）：把项目名和归位前的目录
	// 一起告诉前端，让它说清楚「这是 X 的 worktree，已归到 X 下」，而不是「项目已创建」
	resp := gin.H{"key": key, "dir": dir, "git": git, "created": created}
	if !created {
		resp["name"] = a.Projects.Name(key)
		if b.Dir != "" && filepath.Clean(b.Dir) != dir {
			resp["worktree"] = filepath.Clean(b.Dir)
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": resp})
}

// cloneMaxWait 克隆最多等多久。10 秒是给「读一下本地目录」用的，克隆完全是另一个量级：
// 大仓库几分钟很正常，用那个超时会把每一次稍大的克隆都判成失败——而它其实还在跑，
// 只是没人等它了，留下半个目录。
const cloneMaxWait = 15 * time.Minute

// cloneInto 把 url 克隆进 dir。
//
// **不走 shell**：URL 是用户输入，拼进 sh -c 就是一个命令注入口子。
// exec.Command 直接传参数，任何引号反引号都只是普通字符。
func cloneInto(parent context.Context, url, dir string) error {
	if st, err := os.Stat(dir); err == nil {
		if !st.IsDir() {
			return fmt.Errorf("%s 已存在且不是目录", dir)
		}
		// 已存在的目录必须是空的：git clone 进非空目录会失败，
		// 但那句报错（"destination path already exists and is not an empty directory"）
		// 对着一个刚点了「新建项目」的人说不清楚发生了什么。
		ents, err := os.ReadDir(dir)
		if err != nil {
			return err
		}
		if len(ents) > 0 {
			return fmt.Errorf("目录 %s 已存在且非空，换一个位置或先清空它", dir)
		}
	} else if err := os.MkdirAll(filepath.Dir(dir), 0o755); err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(parent, cloneMaxWait)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", "clone", "--", url, dir)
	// 非交互：URL 写错或私库没配好凭证时，git 会停在终端上等用户名密码，
	// 而这里没有终端 —— 不关掉就是干等到超时。
	cmd.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0", "GIT_ASKPASS=", "SSH_ASKPASS=")
	out, err := cmd.CombinedOutput()
	if err == nil {
		return nil
	}
	// clone 失败会留下半个目录，不清掉的话用户重试会撞上「已存在且非空」。
	if ents, e := os.ReadDir(dir); e == nil && len(ents) > 0 {
		_ = os.RemoveAll(dir)
	}
	msg := strings.TrimSpace(string(out))
	if ctx.Err() == context.DeadlineExceeded {
		return fmt.Errorf("克隆超时（超过 %s）：%s", cloneMaxWait, msg)
	}
	if msg == "" {
		return err
	}
	return fmt.Errorf("%s", msg)
}

// ProjectDelete DELETE /projects/:key
// 纯台账操作：从项目列表移除，不动目录/worktree/会话；有会话在跑的仓库
// 下次聚合会被发现通道重新记入（这是特性——项目列表反映实况）。
func (a *API) ProjectDelete(c *gin.Context) {
	if _, ok := a.Projects.Dir(c.Param("key")); !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "UNKNOWN_PROJECT"}})
		return
	}
	a.Projects.Remove(c.Param("key"))
	projRespMu.Lock()
	projResp = nil
	projRespMu.Unlock()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// ProjectActivity GET /projects/:key/activity —— 活动流：全部分支近 30 天提交（60s 缓存）
func (a *API) ProjectActivity(c *gin.Context) {
	dir, ok := a.Projects.Dir(c.Param("key"))
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "UNKNOWN_PROJECT"}})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 15*time.Second)
	defer cancel()
	entries, err := a.WT.RecentLog(ctx, dir)
	if err != nil {
		if we, ok := err.(*worktree.Err); ok && we.Code == "NOT_GIT_REPO" {
			entries = nil // 非 git 项目：无 git log，仍可有留痕
		} else {
			wtErr(c, err)
			return
		}
	}
	// 活动流 = git log ∪ 收尾留痕（08 §2.2：丢弃后的提交不可达，留痕保住摘要）
	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"commits": entries,
		"traces":  a.Projects.ReadTrace(dir, 50),
	}})
}

// ProjectPrefs PATCH /projects/:key/prefs {pinned?, displayName?, defaultAgent?, defaultBase?}
func (a *API) ProjectPrefs(c *gin.Context) {
	var b struct {
		Pinned       *bool   `json:"pinned"`
		DisplayName  *string `json:"displayName"`
		DefaultAgent *string `json:"defaultAgent"`
		DefaultBase  *string `json:"defaultBase"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	ok := a.Projects.SetPrefs(c.Param("key"), func(p *project.Prefs) {
		if b.Pinned != nil {
			p.Pinned = *b.Pinned
		}
		if b.DisplayName != nil {
			p.DisplayName = *b.DisplayName
		}
		if b.DefaultAgent != nil {
			p.DefaultAgent = *b.DefaultAgent
		}
		if b.DefaultBase != nil {
			p.DefaultBase = *b.DefaultBase
		}
	})
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "UNKNOWN_PROJECT"}})
		return
	}
	projRespMu.Lock()
	projResp = nil // 偏好变更立即反映到下一次列表
	projRespMu.Unlock()
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// summarizeSessions 把一个项目的会话汇总进 summary：**先在全量上统计，再截断给卡片**。
//
// 反过来做会漏。Top 只留三行给卡片画，而前端一度拿它数 waiting/running、挑「需要你」——
// 于是一个有 4 个以上活跃会话的项目里，排第 4 的那个「等待输入」会从行动队列和页头计数里
// 凭空消失，默认排序也跟着失真。计数走 Running/Waiting，队列走 Needs，Top 只管画。
func summarizeSessions(p *projectSummary, top []projectSession) {
	p.Running, p.Waiting, p.Needs = 0, 0, nil
	for _, s := range top {
		if s.Running {
			p.Running++
		}
		if s.Waiting {
			p.Waiting++
			p.Needs = append(p.Needs, s)
		}
	}
	sort.Slice(p.Needs, func(i, j int) bool { return p.Needs[i].LastActivity > p.Needs[j].LastActivity })

	sort.Slice(top, func(i, j int) bool {
		// 等待输入的排最前：卡片只画三行，而「有人在等你」是这三行里最该被看见的一行
		if top[i].Waiting != top[j].Waiting {
			return top[i].Waiting
		}
		if top[i].Attached != top[j].Attached {
			return top[i].Attached
		}
		return top[i].LastActivity > top[j].LastActivity
	})
	if len(top) > 3 { // 卡片画三行；截到 2 就逼得前端自己再拉一遍会话列表拼
		top = top[:3]
	}
	p.Top = top
}
