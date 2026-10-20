// devtools.go：把 Chrome 自带的 DevTools 前端（即本地按 F12 看到的那套调试界面）
// 反向代理给用户浏览器打开。
//
// 镜像端只看到画面帧，真正的 F12 由 Chrome 调试端口直接提供：
//
//	/devtools/inspector.html        DevTools 前端静态资源
//	/devtools/page/<tabId>          该标签页的 CDP WebSocket（DevTools 连它干活）
//
// 二者都在 127.0.0.1:9222，用户浏览器够不到 → 经本代理转发：
//
//	/api/browser/cdp/*  →  http://127.0.0.1:9222/*
//
// httputil.ReverseProxy 自 Go 1.12 起原生支持 WebSocket 升级，HTTP 资源与
// CDP 帧通道一把代理即可。两处关键改写见 Director。
package browser

import (
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"

	"github.com/gin-gonic/gin"
)

const cdpPrefix = "/api/browser/cdp"

var devtoolsProxy = newDevtoolsProxy()

func newDevtoolsProxy() *httputil.ReverseProxy {
	u, _ := url.Parse(cdpAddress()) // http://127.0.0.1:9222
	p := httputil.NewSingleHostReverseProxy(u)
	p.Director = func(req *http.Request) {
		u, _ := url.Parse(cdpAddress())
		req.URL.Scheme, req.URL.Host = u.Scheme, u.Host
		// Chrome 调试端口有 DNS-rebind 防护：Host 必须是 IP/localhost，否则 500。
		req.Host = u.Host
		// 去 Origin：Chrome 的 remote-allow-origins 校验仅在带 Origin 时生效；
		// 删掉它即按「非浏览器请求」放行，兼容未开 --remote-allow-origins=* 的外部 Chrome。
		req.Header.Del("Origin")
		// 剥掉本代理前缀：/api/browser/cdp/devtools/... → /devtools/...
		req.URL.Path = strings.TrimPrefix(req.URL.Path, cdpPrefix)
		if req.URL.Path == "" {
			req.URL.Path = "/"
		}
		req.URL.RawPath = "" // 让 EscapedPath 重新基于改写后的 Path 计算
	}
	return p
}

// DevToolsProxy 把 /api/browser/cdp/* 透传给 Chrome 调试端口（含 DevTools 前端与 CDP ws）。
func DevToolsProxy(c *gin.Context) {
	if err := ensureChrome(); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error()}})
		return
	}
	devtoolsProxy.ServeHTTP(c.Writer, c.Request)
}
