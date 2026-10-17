package server

import (
	"context"
	"net/http"
	"path/filepath"
	"time"

	"github.com/gin-gonic/gin"
	"ttmux-web/auth"
	"ttmux-web/cluster/hub"
)

// NewHub 装配**中心** 的 Gin 引擎。它**不复用 New()**——不构造业务 runtime、
// 不启动 SyncLoop、不初始化 browser / phone / pty，只做：用户认证入口、静态资源（控制台）、
// 节点隧道接入、中心本地 API（/api/hub/*）、以及把 /n/:nodeId/* 反代进目标节点。
// 见 docs/design/cluster/architecture.html §1。
func NewHub(cfg Config) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.UseRawPath = true
	r.Use(gin.Recovery())

	a := auth.New(cfg.Password, cfg.TOTPSecret, cfg.TOTPState, cfg.LockAfter, cfg.LockSecs, cfg.SavePassword)
	brk := hub.New(filepath.Join(cfg.DataDir, "cluster"))
	brk.SetPublicURL(cfg.Cluster.PublicURL)
	brk.SetEnrollTTL(time.Duration(cfg.Cluster.EnrollTTLMin) * time.Minute)
	brk.SetVersion(cfg.Version)
	// 采样在这里起而不是 New() 里：测试会造很多个 Hub，每个都拖一条后台 goroutine 的话，
	// goroutine 泄漏那条回归用例自己就先花了。
	brk.StartSampling(context.Background())

	// 公开端点（与单机一致：登录 / 首次设置 / 版本 / 证书 / 导航页）
	mountPublic(r, a, cfg)

	// 节点出站隧道接入（token 鉴权，非用户会话）。
	r.GET("/cluster/tunnel", brk.HandleTunnel)

	// 用户会话下的最小 /api（控制台探活用；业务 API 一律经 /n/<id> 代理到节点）。
	g := r.Group("/api", a.Middleware())
	g.Use(func(c *gin.Context) { c.Header("Cache-Control", "no-store") })
	g.GET("/me", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}}) })

	// 多机设置：中心这边也得能改角色——否则切成中心之后就再也切不回来了（只能手改 yaml）。
	cl := &clusterAPI{cfgPath: cfg.ConfigPath, cluster: cfg.Cluster, bind: cfg.Bind, tls: cfg.TLSEnabled}
	g.GET("/cluster/config", cl.Get)
	g.PUT("/cluster/config", cl.Put)
	g.POST("/cluster/restart", cl.Restart)

	// 中心本地 API：节点列表 / bootstrap / 接入签发（用户会话鉴权）。
	bg := r.Group("/api/hub", a.Middleware())
	bg.Use(func(c *gin.Context) { c.Header("Cache-Control", "no-store") })
	bg.GET("/nodes", brk.Nodes)
	// 中心自身的健康与事件（中心页）。诊断口 pprof 不走这里：它只绑回环，见 cluster/hub/self.go
	bg.GET("/self", brk.Self)
	bg.GET("/bootstrap", brk.Bootstrap)
	bg.POST("/enroll", brk.Enroll)

	// 节点反代：/n/:nodeId/*path（用户会话鉴权后转发进目标节点隧道）。
	ng := r.Group("/n/:nodeId", a.Middleware())
	ng.Any("/*path", brk.ProxyNode)

	mountWeb(r, cfg.FrontendDir, nil)
	return r
}
