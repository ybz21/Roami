// Package api 实现各资源的 HTTP handler（sessions / tasks / env / info / fs）。
// 全部通过 ttmux.Client 转发到 CLI，自身不含编排逻辑。
package api

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"ttmux-web/internal/id"
	"ttmux-web/internal/metadb"
	"ttmux-web/project"
	"ttmux-web/race"
	"ttmux-web/search"
	"ttmux-web/ttmux"
	"ttmux-web/worktree"
)

// labelOption 会话展示名所在的 tmux 用户选项（与 CLI 侧 runtime.LabelOption 同名，
// 两个 module 各留一份常量——跨模块 import 要把一串 replace 抄进 backend/go.mod，
// 为一个字符串不值当；e2e 与 CLI 单测各有断言防漂）。
const labelOption = "@roam_name"

type API struct {
	TT          *ttmux.Client
	WT          *worktree.Service // Worktree 领域服务（独占 git worktree 操作）
	BrowserHome string            // 浏览器导航起始页地址（供前端设为默认主页）
	Football    *FootballStore
	Speech      *SpeechStore      // 语音识别(ASR)配置 + 转录
	Prefs       *PreferencesStore // 用户偏好（主题/语言/Agent 命令等）
	Push        *PushStore        // Web Push：VAPID 密钥 + 设备订阅（api/push.go）
	Inbox       *InboxStore       // 收件箱：会话事件 + 已读（api/inbox.go）
	Races       *race.Store       // 竞赛（W5/W6）业务数据模型
	Projects    *project.Store    // 项目（08）：knownRepos 弱台账 + UI 偏好
	FileIndex   *search.FileIndex // 全局搜索（⌘K）的项目文件名索引，见 search.go
	Meta        *metadb.DB        // 台账库直连；降级时各 store 自动退回 JSON
	agentLink   *agentLinker      // 把手敲起来的 claude 会话认到它那段对话上
}

// New 组装 API。台账库的握手在这里做一次：库的位置由 ttmux 报，不是后端自己拼
// （ROAM_DATA 与 ROAM_HOME 可以指到不同地方，自己拼会开出一个空库）。
// 握手失败不阻断启动——终端、文件、浏览器这些和台账无关的功能不该被连坐。
func New(tt *ttmux.Client, browserHome, dataDir, fallbackBin string) *API {
	meta := metadb.Open(context.Background(), tt, fallbackBin)
	// 三个 store 都从库里读到数据之后，才把旧 JSON 退休——顺序反了会让后端
	// 下一次 save() 原地复活一个新 JSON，跟库分叉。
	defer func() {
		if meta.OK() {
			metadb.RetireLegacyFiles(dataDir)
		}
	}()
	return &API{TT: tt, WT: worktree.New(dataDir, meta), BrowserHome: browserHome,
		Football: NewFootballStore(), Speech: NewSpeechStore(dataDir),
		Prefs: NewPreferencesStore(dataDir), Races: race.NewStore(dataDir, meta),
		Push: NewPushStore(dataDir), Inbox: NewInboxStore(dataDir, func() *sql.DB {
			if meta.OK() {
				return meta.SQL()
			}
			return nil
		}),
		Projects: project.NewStore(dataDir, meta), FileIndex: search.NewFileIndex(), Meta: meta,
		agentLink: newAgentLinker()}
}

// json 透传 ttmux 的 --json 输出
func (a *API) json(c *gin.Context, args ...string) {
	// 只认 stdout。日志走 stderr（插件 SDK 的 Logf 就是这么写的），混进来会让整份
	// 响应不再是 JSON，浏览器那边只剩一句「Unexpected token 'r'」——定时任务保存
	// 明明成功了，界面上却是一条报错，就是这么来的。
	out, errOut, err := a.TT.RunJSON(args...)
	if err != nil {
		msg := strings.TrimSpace(ttmux.StripANSI(errOut))
		if msg == "" {
			msg = ttmux.StripANSI(out)
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TTMUX_ERROR", "message": msg}})
		return
	}
	body := strings.TrimSpace(ttmux.StripANSI(out))
	if !json.Valid([]byte(body)) {
		// 命令说自己成功了，吐的却不是 JSON。把 stderr 原样报出去：那里通常写着原因，
		// 而前端拿到半截 JSON 只会抛解析错，把真正的话盖掉。
		msg := strings.TrimSpace(ttmux.StripANSI(errOut))
		if msg == "" {
			msg = firstLine(body)
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "BAD_JSON", "message": msg}})
		return
	}
	c.Data(http.StatusOK, "application/json; charset=utf-8", []byte(body))
}

// firstLine 截第一行给错误消息用：命令失败时输出可能是一整屏。
func firstLine(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return s[:i]
	}
	return s
}

// text 返回写操作的纯文本结果（去 ANSI）
func (a *API) text(c *gin.Context, args ...string) {
	out, err := a.TT.Run(args...)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TTMUX_ERROR", "message": ttmux.StripANSI(out)}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": ttmux.StripANSI(out)})
}

func (a *API) Me(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"authed": true, "browserHome": a.BrowserHome}})
}

// Info 透传 ttmux info，并补一个 metaDb 字段说明台账走的是库还是降级的 JSON。
// **只增字段不改既有字段**，前端不用动；降级时用户能在界面上看见原因，
// 而不是「项目卡为什么没有历史」查不出所以然。
func (a *API) Info(c *gin.Context) {
	out, err := a.TT.Run("info", "--json")
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TTMUX_ERROR", "message": ttmux.StripANSI(out)}})
		return
	}
	var payload map[string]any
	if json.Unmarshal([]byte(out), &payload) != nil {
		c.Data(http.StatusOK, "application/json", []byte(out))
		return
	}
	meta := gin.H{"mode": string(a.Meta.Mode())}
	if a.Meta.OK() {
		meta["schemaVersion"] = a.Meta.Info().Version
		meta["path"] = a.Meta.Info().Path
	} else if why := a.Meta.Why(); why != "" {
		meta["error"] = why
	}
	payload["metaDb"] = meta
	c.JSON(http.StatusOK, payload)
}

// FS 列出目录下的子目录，供前端选择工作目录
func (a *API) FS(c *gin.Context) {
	p := c.Query("path")
	if p == "" {
		if home, err := os.UserHomeDir(); err == nil {
			p = home
		} else {
			p = "/"
		}
	}
	p = filepath.Clean(p)
	entries, err := os.ReadDir(p)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "FS_ERROR", "message": err.Error()}})
		return
	}
	dirs := []string{}
	for _, e := range entries {
		if e.IsDir() && !strings.HasPrefix(e.Name(), ".") {
			dirs = append(dirs, e.Name())
		}
	}
	sort.Strings(dirs)
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"path": p, "parent": filepath.Dir(p), "dirs": dirs}})
}

// SanitizeSessionName 把 tmux 不允许出现在会话名中的字符替换掉。
// tmux 自身会把 '.' 和 ':' 替换为 '_'，这里提前做同样的事，
// 避免后续 -t 引用时 '.' 被解析为 session.window.pane 分隔符而报错。
func SanitizeSessionName(name string) string {
	return strings.NewReplacer(".", "_", ":", "_").Replace(name)
}

// sessionParam 读取路由 :name 参数并净化（点号/冒号 → 下划线）。
func sessionParam(c *gin.Context) string {
	return SanitizeSessionName(c.Param("name"))
}

// sessionTarget 路由 :name → tmux 会话名（= 会话 id）。
//
// 前端一律传会话名，此时是 id 格式，直接返回、零开销；只有老页面/外部脚本/老书签
// 传来「展示名」时才问一次 tmux 换算（会话名与 @roam_name 各比一遍）。
func (a *API) sessionTarget(c *gin.Context) string {
	return a.resolveSession(sessionParam(c))
}

func (a *API) resolveSession(token string) string {
	if token == "" || id.Valid(token) {
		return token
	}
	out, err := a.TT.Run("list-sessions", "-F", "#{session_name}\t#{"+labelOption+"}")
	if err != nil {
		return token
	}
	byLabel := ""
	for _, line := range strings.Split(strings.TrimSpace(ttmux.StripANSI(out)), "\n") {
		name, label, _ := strings.Cut(strings.TrimRight(line, "\r"), "\t")
		switch {
		case name == token:
			return name
		case strings.TrimSpace(label) == token && byLabel == "":
			byLabel = name
		}
	}
	if byLabel != "" {
		return byLabel
	}
	return token
}

// Sessions GET /sessions[?tree=1] —— tree=1 返回 parent 投影树（ls --tree --json，
// 节点带 parent/children，供 W2 父子分组）；缺省平铺（兼容旧调用方）。
func (a *API) Sessions(c *gin.Context) {
	if c.Query("tree") == "1" {
		a.json(c, "ls", "--tree", "--json")
		return
	}
	a.json(c, "ls", "--json")
}
func (a *API) NewSession(c *gin.Context) {
	var b struct {
		Name string `json:"name"`
		Dir  string `json:"dir"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || b.Name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	// name 是**展示名**：会话本身叫 id（由 CLI 生成，那里是唯一的 id 出处），
	// 名字只写进 tmux 的 @roam_name。重名、空格、中文都随便。
	sess, err := a.newSession(b.Name, b.Dir)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TTMUX_ERROR", "message": err.Error()}})
		return
	}
	// 在哪个目录建的，就永远属于那个项目——之后终端里 cd 去哪都不改归属。
	// （不等轮询采样才钉：新会话头几秒就 cd 走的话会钉错。）
	a.WT.BindSessionHome(sess, strings.TrimSpace(b.Dir))
	c.JSON(http.StatusOK, gin.H{"data": sess, "name": sess, "label": strings.TrimSpace(b.Name)})
}

// newSession 建一个 detached 会话，返回会话名(= 会话 id)。
// 走 CLI 的 `ttmux new --json` 而不是自己拼 tmux new-session：会话 id 的生成、
// @roam_name 的落地只有一份实现（CLI 侧），后端不再复制一遍。
func (a *API) newSession(label, dir string) (string, error) {
	args := []string{"new", "--json", "--no-reuse", label}
	if d := strings.TrimSpace(dir); d != "" {
		args = append(args, "--dir", d)
	}
	out, err := a.TT.Run(args...)
	if err != nil {
		return "", errors.New(ttmux.StripANSI(out))
	}
	var res struct {
		Session string `json:"session"`
	}
	if json.Unmarshal([]byte(out), &res) != nil || res.Session == "" {
		return "", errors.New(ttmux.StripANSI(out))
	}
	return res.Session, nil
}

// SessionHistory GET /sessions/history —— 已结束的会话。
//
// 会话死了行不删（M2），所以「那天下午干了什么」翻得回来：每条带着原归属目录、
// 展示名快照、结束原因，以及 agent 那一侧的对话 id。
func (a *API) SessionHistory(c *gin.Context) {
	args := []string{"db", "history", "--json"}
	if n := c.Query("limit"); n != "" {
		args = append(args, "--limit", n)
	}
	a.json(c, args...)
}

// SessionRestore POST /sessions/:name/restore —— 按台账重开一个壳。
//
// 重开的是**壳**不是现场：pane 里的进程死了就是死了。同目录、同展示名，
// 有 agent 对话 id 就顺带接回原对话；旧行保持 dead，新会话是新 id。
func (a *API) SessionRestore(c *gin.Context) {
	out, err := a.TT.Run("db", "restore", c.Param("name"), "--json")
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{
			"code": "RESTORE_FAILED", "message": ttmux.StripANSI(out)}})
		return
	}
	var res map[string]string
	if json.Unmarshal([]byte(out), &res) != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{
			"code": "RESTORE_FAILED", "message": ttmux.StripANSI(out)}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": res})
}

// RenameSession PATCH /sessions/:name {name} —— 改会话的**展示名**。
// tmux 会话名是 id、永远不动：终端标签、URL、归属、meta 外键、logs/meta 路径
// 一个都不用跟着搬，重名也无所谓。
func (a *API) RenameSession(c *gin.Context) {
	var b struct {
		Name string `json:"name"`
	}
	sess := a.sessionTarget(c)
	if err := c.ShouldBindJSON(&b); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	label := strings.TrimSpace(b.Name)
	if sess == "" || label == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	out, err := a.TT.Run("rename", sess, label)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TTMUX_ERROR", "message": ttmux.StripANSI(out)}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"name": sess, "label": label}})
}

// 走 ttmux kill --yes（非交互）：孤儿收养/meta 清理在 CLI 内完成；?cascade=1 级联杀子树。
func (a *API) KillSession(c *gin.Context) {
	name := a.sessionTarget(c)
	args := []string{"kill", name, "--yes"}
	if c.Query("cascade") == "1" {
		args = append(args, "--cascade")
	}
	// 不用手动清归属：键是 tmux session_id，同名重建拿到的是新 id，天然不继承旧归属；
	// 死会话的残行由下一轮 sessionHomes 的 reconcile 收敛。这里主动删反而有风险——
	// kill 万一失败，活会话丢了绑定，下次采样会按当时的 cwd 重钉（可能已 cd 走）。
	a.text(c, args...)
}
func (a *API) Capture(c *gin.Context) {
	a.text(c, "capture", a.sessionTarget(c), "--lines", c.DefaultQuery("lines", "200"))
}

// 允许注入的具名按键（其余只允许单个字母/数字）。用于在专业渲染模式下响应 TUI 选择框。
// C-c 是「强制中断」那一档：Esc 只回到 TUI 的输入行，卡在工具里的子进程（长跑的 bash、
// 收不到响应的请求）压根没收到信号，得靠 ^C 才停得下来。
var allowedKeys = map[string]bool{
	"Up": true, "Down": true, "Left": true, "Right": true,
	"Enter": true, "Escape": true, "Tab": true, "Space": true, "BSpace": true,
	"C-c": true,
	// BTab = Shift+Tab：Claude/Codex 用它轮换权限/审批模式，对话页的「+」菜单要发这一枚
	"BTab": true,
}

// Keys POST /sessions/:name/keys —— 向会话注入原始按键（不追加回车）。
// body: {"keys":["Down","Enter"]} 或 {"keys":["2"]}；经白名单校验后 tmux send-keys。
// 之所以单列一个端点：/tasks/_/send 只能发「文本+回车」，无法发方向键/裸数字/Esc，
// 而 Claude/Codex 的权限确认/选项菜单需要这些键来选择。
func (a *API) Keys(c *gin.Context) {
	name := a.sessionTarget(c)
	var b struct {
		Keys []string `json:"keys"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || len(b.Keys) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	// =name: 精确匹配（send-keys 的 pane 目标对裸 =name 报 can't find pane）；走 ttmux 转发尊重 TMUX_BIN
	args := []string{"send-keys", "-t", "=" + name + ":"}
	for _, k := range b.Keys {
		ok := allowedKeys[k]
		if !ok && len(k) == 1 {
			ch := k[0]
			ok = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')
		}
		if !ok {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_KEY", "message": k}})
			return
		}
		args = append(args, k)
	}
	if out, err := a.TT.Run(args...); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TMUX_ERROR", "message": ttmux.StripANSI(out)}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}

// SessionCwd GET /sessions/:name/cwd —— 返回会话活动 pane 的工作目录（供文件侧栏定位根）。
// 走 ttmux 转发（尊重 TMUX_BIN）+ =name 精确匹配；display-message 对 =name 静默输出空，
// 所以用 list-panes 取 active pane（与 fork 的父 cwd 解析同款）。
func (a *API) SessionCwd(c *gin.Context) {
	dir := ""
	if out, err := a.TT.Run("list-panes", "-t", "="+a.sessionTarget(c), "-F", "#{pane_active}\t#{pane_current_path}"); err == nil {
		for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
			active, cwd, ok := strings.Cut(line, "\t")
			if ok && (dir == "" || active == "1") {
				dir = cwd
			}
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"dir": dir}})
}

// SessionType POST /sessions/:name/type —— 把文本字面量打进当前 pane（不追加回车）。
// 供终端页语音识别后回填用：内容停在输入行，用户复查/编辑后自行按 Enter 发送。
func (a *API) SessionType(c *gin.Context) {
	name := a.sessionTarget(c)
	var b struct {
		Text string `json:"text"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || b.Text == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	a.text(c, "send-keys", "-t", name, "-l", b.Text)
}

// Tasks（命令 + Agent 统一）
func (a *API) Tasks(c *gin.Context)       { a.json(c, "group", "ls", "--json") }
func (a *API) TaskStatus(c *gin.Context)  { a.json(c, "status", c.Param("g"), "--json") }
func (a *API) TaskCollect(c *gin.Context) { a.json(c, "collect", c.Param("g"), "--json") }
func (a *API) TaskKill(c *gin.Context)    { a.text(c, "group", "kill", c.Param("g")) }

func (a *API) Send(c *gin.Context) {
	var b struct {
		Sess string `json:"sess"`
		Msg  string `json:"msg"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || b.Sess == "" || b.Msg == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	b.Sess = SanitizeSessionName(b.Sess)
	// 分两步注入：先字面文本(-l，不解释按键名)，停顿一下，再单独回车。
	// 否则像 Codex 这类 TUI 会把「文本+回车」当成一次粘贴，把回车并进去变成换行而非提交。
	if _, err := a.TT.Run("send-keys", "-t", b.Sess, "-l", b.Msg); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TTMUX_ERROR", "message": ttmux.StripANSI(err.Error())}})
		return
	}
	time.Sleep(90 * time.Millisecond)
	a.text(c, "send-keys", "-t", b.Sess, "Enter")
}

func (a *API) Spawn(c *gin.Context) {
	var b struct {
		Group string `json:"group"`
		Type  string `json:"type"`
		Tasks []struct {
			Name string `json:"name"`
			Cmd  string `json:"cmd"`
			Task string `json:"task"`
		} `json:"tasks"`
		Dir      string `json:"dir"`
		Model    string `json:"model"`
		Perm     string `json:"perm"`
		MaxTurns string `json:"maxTurns"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || b.Group == "" || len(b.Tasks) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}

	var args []string
	if b.Type == "agent" {
		args = append(args, "spawn", "--agent", b.Group)
		for _, t := range b.Tasks {
			args = append(args, t.Name, t.Task)
		}
		if b.Dir != "" {
			args = append(args, "--dir", b.Dir)
		}
		if b.Model != "" {
			args = append(args, "--model", b.Model)
		}
		if b.Perm != "" {
			args = append(args, "--perm", b.Perm)
		}
		if b.MaxTurns != "" {
			args = append(args, "--max-turns", b.MaxTurns)
		}
	} else {
		args = append(args, "spawn", b.Group)
		for _, t := range b.Tasks {
			args = append(args, t.Name, t.Cmd)
		}
	}
	a.text(c, args...)
}

// Env
func (a *API) Env(c *gin.Context)       { a.json(c, "env", "--json") }
func (a *API) EnvDelete(c *gin.Context) { a.text(c, "env", "rm", c.Param("key")) }
func (a *API) EnvPush(c *gin.Context)   { a.text(c, "env", "push") }
func (a *API) EnvSet(c *gin.Context) {
	var b struct {
		Key   string `json:"key"`
		Value string `json:"value"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || b.Key == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	a.text(c, "env", "set", b.Key+"="+b.Value)
}
