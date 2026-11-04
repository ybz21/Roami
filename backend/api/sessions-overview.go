package api

// GET /sessions/overview：手机会话页的一条接口（24 稿 §5）。桌面树的原料要三条接口拼，手机上
// worktree 那条又被省了，结果全成散会话。这里把会话 + 归属（项目 / worktree / 分支）+ 探测循环
// 5s 一轮攒下的活状态（agent / 等你 / 最近一句）一次给全。

import (
	"context"
	"encoding/json"
	"net/http"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// liveSnap 探测循环每轮写一份：会话此刻在干什么
type liveSnap struct {
	Prompt  *notificationPrompt
	Agent   string // claude | codex | pi | opencode | ""
	Busy    bool   // agent 正在响应；进程停在提示符时不算“在跑”
	Waiting bool
	YesNo   bool // 等的是「允许 / 拒绝」这种二选一，首页能直接给两个按钮；自由选择题不给
	Tail    string
	At      time.Time
}

func (s liveSnap) running() bool { return s.Agent != "" && s.Busy && !s.Waiting }

func (a *API) sessionRunning(name, agent, screen string, waiting bool) bool {
	if waiting || agent == "" {
		return false
	}
	if snap, ok := a.Live.get(name); ok && snap.Agent == agent && time.Since(snap.At) < 15*time.Second {
		return snap.running()
	}
	return screenBusy(screen)
}

type liveTable struct {
	mu sync.RWMutex
	m  map[string]liveSnap
}

func (l *liveTable) set(name string, s liveSnap) {
	l.mu.Lock()
	if l.m == nil {
		l.m = map[string]liveSnap{}
	}
	l.m[name] = s
	l.mu.Unlock()
}

func (l *liveTable) get(name string) (liveSnap, bool) {
	l.mu.RLock()
	defer l.mu.RUnlock()
	s, ok := l.m[name]
	return s, ok
}

func (l *liveTable) prune(alive map[string]string) {
	l.mu.Lock()
	for k := range l.m {
		if _, ok := alive[k]; !ok {
			delete(l.m, k)
		}
	}
	l.mu.Unlock()
}

type overviewItem struct {
	SelectionMode string               `json:"selectionMode,omitempty"`
	Prompt        string               `json:"prompt,omitempty"`
	Choices       []NotificationChoice `json:"choices,omitempty"`
	WaitingBody   string               `json:"waitingBody,omitempty"`
	Name          string               `json:"name"`
	Label         string               `json:"label"`
	LastActivity  int64                `json:"lastActivity"`
	Dormant       bool                 `json:"dormant"`
	ProjectKey    string               `json:"projectKey,omitempty"`
	Project       string               `json:"project,omitempty"`
	ProjectDir    string               `json:"projectDir,omitempty"`
	Worktree      string               `json:"worktree,omitempty"`
	Branch        string               `json:"branch,omitempty"`
	Agent         string               `json:"agent,omitempty"`
	Running       bool                 `json:"running"`
	Waiting       bool                 `json:"waiting"`
	Tail          string               `json:"tail,omitempty"`
	YesNo         bool                 `json:"yesNo,omitempty"`
}

func (a *API) SessionsOverview(c *gin.Context) {
	out, err := a.TT.Run("ls", "--json")
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"code": "TTMUX", "message": err.Error()}})
		return
	}
	var list []sessListItem
	_ = json.Unmarshal([]byte(out), &list)
	ctx, cancel := context.WithTimeout(c.Request.Context(), 8*time.Second)
	defer cancel()
	ann := a.WT.Annotations(ctx)
	// 项目：按目录认，主仓库根和非 git 项目目录都可能是归属点
	byDir := map[string]struct{ key, name, dir string }{}
	for key, e := range a.Projects.Entries() {
		name := e.DisplayName
		if name == "" {
			name = filepath.Base(e.Dir)
		}
		byDir[filepath.Clean(e.Dir)] = struct{ key, name, dir string }{key, name, e.Dir}
	}
	items := make([]overviewItem, 0, len(list))
	for _, s := range list {
		if strings.HasPrefix(s.Name, "_ttmux-") {
			continue
		}
		it := overviewItem{Name: s.Name, Label: s.Label, LastActivity: rawInt(s.LastActivity), Dormant: s.State == "dormant"}
		if it.Label == "" {
			it.Label = s.Name
		}
		if an := ann[s.Name]; an != nil {
			dir := an.Home
			if an.Primary != nil {
				it.Branch = an.Primary.Branch
				if an.Primary.Linked {
					it.Worktree = an.Primary.Worktree
				}
				dir = an.Primary.Repo
			}
			// 主仓库根命中项目；没命中就按 home 目录最长前缀找非 git 项目
			if p, ok := byDir[filepath.Clean(dir)]; ok {
				it.ProjectKey, it.Project, it.ProjectDir = p.key, p.name, p.dir
			} else {
				best := ""
				for d, p := range byDir {
					if strings.HasPrefix(filepath.Clean(an.Home)+"/", d+"/") && len(d) > len(best) {
						best = d
						it.ProjectKey, it.Project, it.ProjectDir = p.key, p.name, p.dir
					}
				}
			}
		}
		if snap, ok := a.Live.get(s.Name); ok {
			it.Agent, it.Waiting, it.Tail = snap.Agent, snap.Waiting, snap.Tail
			it.YesNo = snap.Waiting && snap.YesNo
			it.Running = snap.running()
			if snap.Waiting && snap.Prompt != nil {
				it.Prompt, it.Choices, it.WaitingBody = snap.Prompt.token(), snap.Prompt.Choices, snap.Prompt.body()
				it.SelectionMode = snap.Prompt.selectionMode()
			}
		}
		items = append(items, it)
	}
	sort.SliceStable(items, func(i, j int) bool { return items[i].LastActivity > items[j].LastActivity })
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"items": items}})
}
