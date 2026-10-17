// 蜂群(swarm) 资源的 HTTP handler —— 全部通过 ttmux.Client 转发到 CLI，自身不含编排逻辑。
// 读 = roami session swarm ... --json；写 = 对应子命令。路径/字段都作独立 argv 传入，杜绝命令注入。
// Web 端只读 + 广场/看板轻操作；建群/加成员/接管/标记成员完成等重编排仍只在 CLI/终端。
package api

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// GET /api/swarms —— 蜂群列表
func (a *API) Swarms(c *gin.Context) { a.json(c, "swarm", "ls", "--json") }

// POST /api/swarms —— 新建蜂群（默认自带 Leader；master=false 则 --no-master，字段名为历史兼容）
func (a *API) SwarmNew(c *gin.Context) {
	var b struct {
		Name     string   `json:"name"`
		Goal     string   `json:"goal"`
		Dir      string   `json:"dir"` // 工作目录(可空)：建群即 mkdir，Leader/上传都落到这里
		Master   *bool    `json:"master"`
		Roster   []string `json:"roster"`   // 项目页发起：班子建议（仅进开场白，09 §4）
		Worktree bool     `json:"worktree"` // 项目页发起：成员独立 worktree 约定（仅进开场白）
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Name) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	args := []string{"swarm", "new", b.Name}
	if b.Goal != "" {
		args = append(args, "--goal", b.Goal)
	}
	if strings.TrimSpace(b.Dir) != "" {
		args = append(args, "--dir", b.Dir)
	}
	if b.Master != nil && !*b.Master {
		args = append(args, "--no-master")
	} else if p := renderLeaderKickoff(promptCtx{
		Swarm: b.Name, Goal: b.Goal, Member: "cc-" + b.Name,
		Workdir: b.Dir, SkillsDir: skillsDir(),
		Roster: b.Roster, WorktreePolicy: b.Worktree,
	}); p != "" {
		// 自动拉起的 Leader 用 auto_leader.md.tmpl 当开场白（含目标/工作目录/可用 skill/职责），
		// 而不是裸 /cc-swarm —— 否则 Leader 容易自己闷头实现、不拆任务派活。
		args = append(args, "--leader-prompt", p)
	}
	a.text(c, args...)
}

// POST /api/swarms/:n/adopt —— 拉起/接管 Leader（指挥）会话。
// 用于「先建群+上传文档、再起 Leader」的时序：建群时传 master=false，上传完文档后再调本接口。
func (a *API) SwarmAdopt(c *gin.Context) {
	var b struct {
		Dir      string   `json:"dir"`
		Roster   []string `json:"roster"` // 与 SwarmNew 同款（先建群传文档再 adopt 的时序不丢上下文）
		Worktree bool     `json:"worktree"`
	}
	_ = c.ShouldBindJSON(&b) // body 可空
	n := c.Param("n")
	args := []string{"swarm", "adopt", n}
	if strings.TrimSpace(b.Dir) != "" {
		args = append(args, "--dir", b.Dir)
	}
	// 取 goal 渲染 Leader 开场白（auto_leader.md.tmpl），随 --prompt 下发
	goal := ""
	if out, err := a.TT.Run("swarm", "status", n, "--json"); err == nil {
		var st struct {
			Goal string `json:"goal"`
		}
		_ = json.Unmarshal([]byte(out), &st)
		goal = st.Goal
	}
	if p := renderLeaderKickoff(promptCtx{
		Swarm: n, Goal: goal, Member: "cc-" + n,
		Workdir: b.Dir, SkillsDir: skillsDir(),
		Roster: b.Roster, WorktreePolicy: b.Worktree,
	}); p != "" {
		args = append(args, "--prompt", p)
	}
	a.text(c, args...)
}

// POST /api/swarms/:n/members —— 加成员(默认 agent cc)
func (a *API) SwarmAddMember(c *gin.Context) {
	var b struct {
		Name    string `json:"name"`
		Type    string `json:"type"`
		Task    string `json:"task"`
		Dir     string `json:"dir"`
		Deps    string `json:"deps"`
		Model   string `json:"model"`
		Perm    string `json:"perm"`
		Kind    string `json:"kind"`    // claude(默认) | codex
		Role    string `json:"role"`    // leader | member（兼容 master | worker，空=后端按"首个 agent 成员→leader"决定）
		Subrole string `json:"subrole"` // 细分角色 key（pm/frontend/qa…，自定义原样）
		Duty    string `json:"duty"`    // 长期职责
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Name) == "" || strings.TrimSpace(b.Task) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	n := c.Param("n")
	typ := b.Type
	if typ == "" {
		typ = "agent"
	}
	kind := b.Kind
	if kind == "" {
		kind = "claude"
	}

	// 查蜂群状态：取 goal / 现有成员 / 是否已有 master
	var st struct {
		Goal    string `json:"goal"`
		Members []struct {
			Name string `json:"name"`
			Role string `json:"role"`
		} `json:"members"`
	}
	if out, err := a.TT.Run("swarm", "status", n, "--json"); err == nil {
		_ = json.Unmarshal([]byte(out), &st)
	}

	role := b.Role
	if role == "" {
		hasMaster := false
		for _, m := range st.Members {
			if m.Role == "leader" || m.Role == "master" {
				hasMaster = true
				break
			}
		}
		if typ == "agent" && !hasMaster {
			role = "leader"
		} else {
			role = "member"
		}
	}
	if role == "master" || role == "lead" {
		role = "leader"
	}
	if role == "worker" {
		role = "member"
	}

	// agent 成员：按角色渲染提示词模板，把原始任务包成完整 prompt（含 skill/swarm 协作格式）
	task := b.Task
	if typ == "agent" {
		var peers []string
		var masterName string
		for _, m := range st.Members {
			if m.Name != b.Name {
				peers = append(peers, m.Name)
			}
			if m.Role == "leader" || m.Role == "master" {
				masterName = m.Name
			}
		}
		if p := renderMemberPrompt(promptCtx{
			Swarm: n, Goal: st.Goal, Member: b.Name, Role: role, Kind: kind,
			Task: b.Task, Deps: b.Deps, Workdir: b.Dir, SkillsDir: skillsDir(),
			MasterName: masterName, Peers: peers,
			Subrole: b.Subrole, Duty: b.Duty,
		}); p != "" {
			task = p
		}
	}

	args := []string{"swarm", "add", n, b.Name, "--type", typ}
	if typ == "agent" {
		args = append(args, "--kind", kind, "--role", role)
		if b.Subrole != "" {
			args = append(args, "--subrole", b.Subrole)
		}
		if b.Duty != "" {
			args = append(args, "--duty", b.Duty)
		}
	}
	if b.Dir != "" {
		args = append(args, "--dir", b.Dir)
	}
	if b.Deps != "" {
		args = append(args, "--depends-on", b.Deps)
	}
	if b.Model != "" {
		args = append(args, "--model", b.Model)
	}
	if b.Perm != "" {
		args = append(args, "--perm", b.Perm)
	}
	args = append(args, task)
	a.text(c, args...)
}

// POST /api/swarms/:n/done —— 标记成员完成(解锁下游)；body 无 member 则标整群完成
func (a *API) SwarmDone(c *gin.Context) {
	var b struct {
		Member string `json:"member"`
	}
	_ = c.ShouldBindJSON(&b)
	if b.Member != "" {
		a.text(c, "swarm", "done", c.Param("n"), b.Member)
		return
	}
	a.text(c, "swarm", "done", c.Param("n"))
}

// POST /api/swarms/:n/activate —— 解锁挂起成员(可指定成员 + --force)
func (a *API) SwarmActivate(c *gin.Context) {
	var b struct {
		Member string `json:"member"`
		Force  bool   `json:"force"`
	}
	_ = c.ShouldBindJSON(&b)
	args := []string{"swarm", "activate", c.Param("n")}
	if b.Member != "" {
		args = append(args, b.Member)
	}
	if b.Force {
		args = append(args, "--force")
	}
	a.text(c, args...)
}

// DELETE /api/swarms/:n —— 归档(杀成员会话, 留元数据)。web 不做彻底 rm(需 tty 确认)。
func (a *API) SwarmArchive(c *gin.Context) { a.text(c, "swarm", "archive", c.Param("n")) }

// GET /api/swarms/:n —— 蜂群详情(成员/依赖/挂起 + 看板/广场摘要由前端另取)
func (a *API) SwarmStatus(c *gin.Context) { a.json(c, "swarm", "status", c.Param("n"), "--json") }

// GET /api/swarms/:n/feed?since=&kind=&n= —— 广场消息流(增量轮询用 since)
func (a *API) SwarmFeed(c *gin.Context) {
	args := []string{"swarm", "feed", c.Param("n"), "--json"}
	if s := c.Query("since"); s != "" {
		args = append(args, "--since", s)
	}
	if k := c.Query("kind"); k != "" {
		args = append(args, "--kind", k)
	}
	if n := c.Query("n"); n != "" {
		args = append(args, "-n", n)
	}
	a.json(c, args...)
}

// POST /api/swarms/:n/say —— 广场发言(web 代发固定署名 human)
func (a *API) SwarmSay(c *gin.Context) {
	var b struct {
		Kind string `json:"kind"`
		Re   string `json:"re"`
		Text string `json:"text"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Text) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	args := []string{"swarm", "say", c.Param("n"), "--as", "human"}
	if b.Kind != "" {
		args = append(args, "--kind", b.Kind)
	}
	if b.Re != "" {
		args = append(args, "--re", b.Re)
	}
	// Web 端 human 发言默认是给 Leader 看的控制面消息。CLI 层会把 --to leader
	// 规范化为文本里的 @leader；旧 @master 仍由 CLI 兼容识别。
	args = append(args, "--to", "leader")
	args = append(args, b.Text)
	a.text(c, args...)
}

// GET /api/swarms/:n/board —— 看板(扁平卡片数组, 前端按 col 分组)
func (a *API) SwarmBoard(c *gin.Context) { a.json(c, "swarm", "board", c.Param("n"), "--json") }

// POST /api/swarms/:n/task —— 建卡
func (a *API) SwarmTaskAdd(c *gin.Context) {
	var b struct {
		Title    string `json:"title"`
		Desc     string `json:"desc"`
		Assignee string `json:"assignee"`
		Deps     string `json:"deps"`
		Col      string `json:"col"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Title) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	args := []string{"swarm", "task", "add", c.Param("n"), b.Title}
	if b.Desc != "" {
		args = append(args, "--desc", b.Desc)
	}
	if b.Assignee != "" {
		args = append(args, "--assignee", b.Assignee)
	}
	if b.Deps != "" {
		args = append(args, "--deps", b.Deps)
	}
	if b.Col != "" {
		args = append(args, "--col", b.Col)
	}
	a.text(c, args...)
}

// PATCH /api/swarms/:n/task/:id —— 卡片流转: {move:<列>} 或 {assign:<成员>}
func (a *API) SwarmTaskPatch(c *gin.Context) {
	var b struct {
		Move   string `json:"move"`
		Assign string `json:"assign"`
	}
	if err := c.ShouldBindJSON(&b); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	n, id := c.Param("n"), c.Param("id")
	switch {
	case b.Move != "":
		a.text(c, "swarm", "task", "move", n, id, b.Move)
	case b.Assign != "":
		a.text(c, "swarm", "task", "assign", n, id, b.Assign)
	default:
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST", "message": "need move or assign"}})
	}
}

// DELETE /api/swarms/:n/task/:id —— 删卡
func (a *API) SwarmTaskDelete(c *gin.Context) {
	a.text(c, "swarm", "task", "rm", c.Param("n"), c.Param("id"))
}
