// 插件资源的 HTTP handler —— 全部通过 ttmux.Client 转发到 CLI(v1 backend 不直连
// plugind,见 docs/design/plugin/04 通路⑥)。读 = roami plugin ... --json;
// 写 = 对应子命令。所有参数独立 argv 传入,杜绝命令注入。
package api

import (
	"net/http"
	"os"
	"strings"

	"github.com/gin-gonic/gin"
)

// GET /api/plugins —— 插件列表(含 manifest、贡献点、配置字段声明)
func (a *API) Plugins(c *gin.Context) { a.json(c, "plugin", "ls", "--json") }

// GET /api/plugin/status —— plugind 守护进程与插件会话状态
func (a *API) PluginStatus(c *gin.Context) { a.json(c, "plugin", "status", "--json") }

// POST /api/plugin/daemon/start —— 拉起 plugind(等价终端执行 roami plugin daemon,
// 幂等:已运行则直接返回)
func (a *API) PluginDaemonStart(c *gin.Context) { a.text(c, "plugin", "daemon") }

// POST /api/plugin/install —— 安装插件:multipart 上传 .tgz 包,或 JSON {path}
// 安装本机目录。落到 CLI `roami plugin install <src>`,安装后默认未启用。
func (a *API) PluginInstall(c *gin.Context) {
	if strings.HasPrefix(c.GetHeader("Content-Type"), "multipart/") {
		fh, err := c.FormFile("file")
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
			return
		}
		if !strings.HasSuffix(fh.Filename, ".tgz") && !strings.HasSuffix(fh.Filename, ".tar.gz") {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PACKAGE", "message": "need .tgz / .tar.gz"}})
			return
		}
		tmp, err := os.CreateTemp("", "roam-plugin-upload-*.tgz")
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TMP_FAILED"}})
			return
		}
		tmp.Close()
		defer os.Remove(tmp.Name())
		if err := c.SaveUploadedFile(fh, tmp.Name()); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "SAVE_FAILED", "message": err.Error()}})
			return
		}
		a.text(c, "plugin", "install", tmp.Name())
		return
	}
	var b struct {
		Path string `json:"path"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Path) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	a.text(c, "plugin", "install", b.Path)
}

// DELETE /api/plugins/:id —— 卸载插件。外部插件删文件;内置插件由 CLI 软删
// (tombstone,从列表隐藏、可经恢复入口找回)。?purge=1 连同清除 storage/config。
func (a *API) PluginUninstall(c *gin.Context) {
	args := []string{"plugin", "uninstall", c.Param("id")}
	if p := c.Query("purge"); p == "1" || p == "true" {
		args = append(args, "--purge")
	}
	a.text(c, args...)
}

// GET /api/plugin/removed —— 已卸载待恢复的内置插件(恢复入口列表)
func (a *API) PluginsRemoved(c *gin.Context) { a.json(c, "plugin", "ls", "--removed", "--json") }

// POST /api/plugins/:id/restore —— 恢复被卸载的内置插件
func (a *API) PluginRestore(c *gin.Context) { a.text(c, "plugin", "restore", c.Param("id")) }

// POST /api/plugin/track —— 把会话登记给插件跟踪(如新建会话勾选「结束后自动互审」:
// labels 带 review:auto=true 与 workdir,plugind 在会话退出时通知插件)
func (a *API) PluginTrack(c *gin.Context) {
	var b struct {
		Session string            `json:"session"`
		Plugin  string            `json:"plugin"`
		Labels  map[string]string `json:"labels"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Session) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	args := []string{"plugin", "track", b.Session}
	if strings.TrimSpace(b.Plugin) != "" {
		args = append(args, "--plugin", b.Plugin)
	}
	for k, v := range b.Labels {
		if strings.TrimSpace(k) == "" || strings.Contains(k, "=") {
			continue
		}
		args = append(args, "--label", k+"="+v)
	}
	a.text(c, args...)
}

// GET /api/plugin/findings —— 互审 finding 列表
func (a *API) PluginFindings(c *gin.Context) { a.json(c, "plugin", "findings", "--json") }

// GET /api/plugin/notifications —— 通知流
func (a *API) PluginNotifications(c *gin.Context) { a.json(c, "plugin", "notifications", "--json") }

// POST /api/plugins/:id/enable | disable
func (a *API) PluginSetEnabled(enable bool) gin.HandlerFunc {
	verb := "disable"
	if enable {
		verb = "enable"
	}
	return func(c *gin.Context) { a.text(c, "plugin", verb, c.Param("id")) }
}

// GET /api/plugins/:id/config —— 配置(secret 字段由 CLI 打码)
func (a *API) PluginConfig(c *gin.Context) { a.json(c, "plugin", "config", c.Param("id")) }

// PUT /api/plugins/:id/config —— 覆写配置项;值为空串表示删除该项。
// 前端对打码展示的 secret 字段只在用户改动时才提交,避免把掩码存回去。
func (a *API) PluginConfigSet(c *gin.Context) {
	var b struct {
		Set map[string]string `json:"set"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || len(b.Set) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	id := c.Param("id")
	for k, v := range b.Set {
		k = strings.TrimSpace(k)
		if k == "" {
			continue
		}
		var out string
		var err error
		if strings.TrimSpace(v) == "" {
			out, err = a.TT.Run("plugin", "config", id, "unset", k)
		} else {
			out, err = a.TT.Run("plugin", "config", id, "set", k, v)
		}
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "TTMUX_ERROR", "message": out}})
			return
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}

// GET /api/plugins/:id/audit —— 该插件的审计记录
func (a *API) PluginAudit(c *gin.Context) { a.json(c, "plugin", "audit", c.Param("id"), "--json") }

// POST /api/plugins/:id/run —— 调用插件命令。args 逐项转为 --k v。
// 长任务(如互审)由插件转成 Agent 会话,命令本身应快速返回;Web 端不加
// 额外超时,与 CLI 行为一致。
func (a *API) PluginRun(c *gin.Context) {
	var b struct {
		Command string            `json:"command"`
		Args    map[string]string `json:"args"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Command) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	// 命令必须属于该插件,防止借任意插件 id 调他家命令。命令 ID 前缀是
	// 插件短名(review-mesh.review),而路由参数是全 id(roam.review-mesh):
	// 先做短名前缀的形状校验,再把命令改写成 id 限定形式
	// (roam.review-mesh:review)交给 CLI——归属由注册表按全 id 精确判定
	// 且不回退短名匹配,伪造 publisher(如 evil.review-mesh)的路由 id 会
	// 因查无此插件被拒,不会落到短名撞名的其他插件上。
	id := c.Param("id")
	_, short, ok := strings.Cut(id, ".")
	if !ok || !strings.HasPrefix(b.Command, short+".") {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_COMMAND"}})
		return
	}
	args := []string{"plugin", "run", id + ":" + strings.TrimPrefix(b.Command, short+".")}
	for k, v := range b.Args {
		if strings.TrimSpace(k) == "" {
			continue
		}
		args = append(args, "--"+k, v)
	}
	a.json(c, args...)
}
