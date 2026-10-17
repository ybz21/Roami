// Race Service（设计 07 §3 W5/W6、§4）：竞赛 = 一个 prompt × N 选手，每人一个隔离
// worktree + 会话。业务数据模型（race/winner/crown 阶段）持久化在本层（races.json），
// 不进 SessionMeta 也不进 swarm.db；worktree 实况仍以 Worktree Service 为准。
package api

import (
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/race"
	"github.com/ybz21/Roami/backend/worktree"
	"github.com/ybz21/Roami/internal/id"
)

// killContestant 杀掉选手会话：优先用 tmux session_id 反查它**现在**叫什么（用户
// 可能改过名），拿不到再退回建赛时记下的名字。走 roami session kill 以便清 meta。
func (a *API) killContestant(ct *race.Contestant) {
	name := ct.Session
	if ct.SessionID != "" {
		if live := a.WT.SessionNameByID(ct.SessionID); live != "" {
			name = live
		}
	}
	if name == "" {
		return
	}
	_, _ = a.TT.Run("kill", name, "--yes")
}

// ── handlers ─────────────────────────────────────────────

// RaceCreate POST /races {name, dir, base?, prompt, contestants: [{agent, cmd}]}
// 逐选手编排（先会话后 worktree，同组合 API）：建会话 → 建 worktree（分支
// <竞赛名>-<a/b/c>，即赛道身份，不随 agent 改名）→ cd → 发同一道题。
// 单个选手失败只标记该选手，不拖累其他人。
func (a *API) RaceCreate(c *gin.Context) {
	var b struct {
		Name        string `json:"name"`
		Dir         string `json:"dir"`
		Base        string `json:"base"`
		Prompt      string `json:"prompt"`
		Contestants []struct {
			Agent string `json:"agent"`
			Cmd   string `json:"cmd"` // agent 启动命令（前端偏好，如 claude / codex）
		} `json:"contestants"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || b.Name == "" || strings.TrimSpace(b.Dir) == "" ||
		strings.TrimSpace(b.Prompt) == "" || len(b.Contestants) == 0 || len(b.Contestants) > 5 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST", "message": "name/dir/prompt/contestants(1..5) required"}})
		return
	}
	b.Name = SanitizeSessionName(b.Name)
	ctx, cancel := wtCtx(c)
	defer cancel()

	prepared, err := a.WT.PrepareBase(ctx, b.Dir, b.Base, "")
	if err != nil {
		wtErr(c, err)
		return
	}
	r := &race.Race{
		ID:        id.New(),
		Name:      b.Name,
		Dir:       b.Dir,
		Base:      b.Base,
		Prompt:    b.Prompt,
		CreatedAt: time.Now().Format(time.RFC3339),
		Status:    "running",
	}
	ok := 0
	for i, in := range b.Contestants {
		letter := string(rune('a' + i))
		ct := race.Contestant{
			Label:  b.Name + "-" + letter,
			Agent:  in.Agent,
			Status: "running",
		}
		fail := func(msg string) {
			ct.Status, ct.Error = "failed", msg
			r.Contestants = append(r.Contestants, ct)
		}
		// 选手会话叫 id，`<竞赛>-<字母>` 只是展示名
		sess, err := a.newSession(ct.Label, b.Dir)
		if err != nil {
			fail("session: " + err.Error())
			continue
		}
		ct.Session = sess
		a.WT.BindSessionHome(ct.Session, b.Dir) // 选手会话归属本仓库；cdInto 之后改钉到各自 worktree
		ct.SessionID = a.WT.SessionID(ct.Session)
		wt, err := a.WT.CreateFromBase(ctx, worktree.CreateReq{Dir: b.Dir, Branch: autoBranch(b.Name) + "-" + letter, Base: b.Base, Dirname: sess}, prepared)
		if err != nil {
			_, _ = a.TT.Run("kill", ct.Session, "--yes")
			fail("worktree: " + err.Error())
			continue
		}
		ct.Branch, ct.Path = wt.Branch, wt.Path
		if r.Base == "" {
			r.Base = wt.Base
		}
		if err = a.cdInto(ct.Session, wt.Path); err != nil {
			a.rollbackPreparedSession(ct.Session, wt, true)
			fail("workspace: " + err.Error())
			continue
		}
		if cmd := strings.TrimSpace(in.Cmd); cmd != "" {
			if _, err = a.TT.Run("send", ct.Session, cmd+" "+shellQuote(b.Prompt)); err != nil {
				a.rollbackPreparedSession(ct.Session, wt, true)
				fail("launch: " + err.Error())
				continue
			}
		}

		r.Contestants = append(r.Contestants, ct)
		ok++
	}

	a.Races.Create(r)
	if ok == 0 {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "ALL_FAILED", "message": "no contestant started"}, "data": r})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": r})
}

// RaceList GET /races —— 全量竞赛（前端按仓库/会话自行过滤，worktree 实况另查）。
func (a *API) RaceList(c *gin.Context) {
	list := a.Races.List()
	if list == nil {
		c.JSON(http.StatusOK, gin.H{"data": []any{}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": list})
}

// RaceCrown POST /races/:id/crown {winner, strategy?, cleanup?, expectedHead?}
// crown 状态机：wip-commit → merge → (可选) cleanup 输家；每步完成即持久化，
// 失败返回 {stage, done}，同 winner 重试会跳过已完成阶段续跑。
func (a *API) RaceCrown(c *gin.Context) {
	var b struct {
		Winner       string `json:"winner"` // 选手会话名
		Strategy     string `json:"strategy"`
		Cleanup      bool   `json:"cleanup"`
		ExpectedHead string `json:"expectedHead"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || b.Winner == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	rc, ok := a.Races.Get(c.Param("id"))
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "NOT_FOUND"}})
		return
	}
	var winner *race.Contestant
	for i := range rc.Contestants {
		if rc.Contestants[i].Session == b.Winner {
			winner = &rc.Contestants[i]
		}
	}
	if winner == nil || winner.Status == "failed" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_WINNER"}})
		return
	}
	// 冻结赢家（换人则清空已完成阶段）。之后整个流程只认 rc 这份**快照**：
	// 长耗时的 git 操作绝不带着锁或台账指针进去——那正是此前那个数据竞争的成因。
	rc, err := a.Races.FreezeWinner(rc.ID, b.Winner)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "NOT_FOUND"}})
		return
	}
	done := func(stage string) bool { return race.StageDone(rc, stage) }
	// mark 用返回的新快照替换本地那份，下一次 done() 判的就是最新状态
	mark := func(stage string) {
		if next, err := a.Races.MarkStage(rc.ID, stage); err == nil {
			rc = next
		}
	}

	ctx, cancel := wtCtx(c)
	defer cancel()
	strategy := b.Strategy
	if strategy == "" {
		strategy = "squash"
	}
	fail := func(stage string, err error) {
		if we, ok := err.(*worktree.Err); ok {
			body := gin.H{"code": we.Code, "message": we.Message, "stage": stage, "done": rc.CrownDone}
			for k, v := range we.Extra {
				body[k] = v
			}
			c.JSON(http.StatusConflict, gin.H{"error": body})
			return
		}
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "STAGE_FAILED", "message": err.Error(), "stage": stage, "done": rc.CrownDone}})
	}

	// 确认后漂移校验在冻结时做（wip-commit 会合法地挪 HEAD，不能把 expectedHead 传给 Merge）
	if b.ExpectedHead != "" && !done("wip-commit") {
		if head, err := a.WT.Head(ctx, winner.Path); err == nil && !strings.HasPrefix(head, b.ExpectedHead) {
			fail("freeze", &worktree.Err{Code: "HEAD_MOVED", Message: "winner HEAD changed since confirmation, re-check and retry"})
			return
		}
	}
	if !done("wip-commit") {
		if err := a.WT.CommitAll(ctx, winner.Path, "wip: auto-commit before crown merge (roam race)"); err != nil {
			fail("wip-commit", err)
			return
		}
		mark("wip-commit")
	}
	if !done("merge") {
		if _, err := a.WT.Merge(ctx, worktree.MergeReq{Path: winner.Path, Strategy: strategy}); err != nil {
			fail("merge", err)
			return
		}
		mark("merge")
	}
	if b.Cleanup && !done("cleanup") {
		var errs []string
		for i := range rc.Contestants {
			ct := &rc.Contestants[i]
			if ct.Session == b.Winner {
				continue
			}
			a.killContestant(ct)
			if ct.Path != "" {
				if err := a.WT.Remove(ctx, worktree.RemoveReq{Path: ct.Path, ForceWorktree: true, DeleteBranch: true, ForceDeleteBranch: true, IgnoreSessions: true}); err != nil {
					errs = append(errs, ct.Session+": "+err.Error())
				}
			}
		}
		if len(errs) > 0 {
			fail("cleanup", &worktree.Err{Code: "CLEANUP_PARTIAL", Message: strings.Join(errs, "; ")})
			return
		}
		mark("cleanup")
	}
	if next, err := a.Races.SetStatus(rc.ID, "crowned"); err == nil {
		rc = next
	}
	c.JSON(http.StatusOK, gin.H{"data": rc})
}

// RaceCleanup POST /races/:id/cleanup —— 全部清理：杀所有选手会话 + 强删 worktree/分支。
// 前端确认框负责展示将丢失的改动（实况来自 /git/worktrees），这里按已确认执行。
func (a *API) RaceCleanup(c *gin.Context) {
	rc, ok := a.Races.Get(c.Param("id"))
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "NOT_FOUND"}})
		return
	}
	ctx, cancel := wtCtx(c)
	defer cancel()
	var errs []string
	for i := range rc.Contestants {
		ct := &rc.Contestants[i]
		a.killContestant(ct)
		if ct.Path != "" {
			if _, err := os.Stat(ct.Path); err != nil {
				continue // worktree 已不在（外部删过），幂等跳过
			}
			if err := a.WT.Remove(ctx, worktree.RemoveReq{Path: ct.Path, ForceWorktree: true, DeleteBranch: true, ForceDeleteBranch: true, IgnoreSessions: true}); err != nil {
				errs = append(errs, ct.Session+": "+err.Error())
			}
		}
	}
	if len(errs) > 0 {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "CLEANUP_PARTIAL", "message": strings.Join(errs, "; ")}})
		return
	}
	cleaned, err := a.Races.SetStatus(rc.ID, "cleaned")
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "NOT_FOUND"}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": cleaned})
}

// RaceDelete DELETE /races/:id —— 只删竞赛记录，不动会话/worktree。
func (a *API) RaceDelete(c *gin.Context) {
	if a.Races.Delete(c.Param("id")) {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
		return
	}
	c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "NOT_FOUND"}})
}
