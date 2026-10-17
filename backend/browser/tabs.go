// tabs.go：标签页管理的 REST 接口（全程复用同一台全局 Chrome）。
//
//	GET    /api/browser/tabs        列出标签页
//	POST   /api/browser/tabs        新建标签页（body 可选 {"url": "..."}）
//	DELETE /api/browser/tabs/:id    关闭标签页
package browser

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
)

// Tabs 列出当前所有 page 标签页。
func Tabs(c *gin.Context) {
	if err := ensureBrowserInstance(c.Query("expectedBrowser")); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error()}})
		return
	}
	pages := listPages()
	out := make([]gin.H, 0, len(pages))
	for _, t := range pages {
		out = append(out, gin.H{"id": t.ID, "title": t.Title, "url": t.URL})
	}
	c.JSON(http.StatusOK, gin.H{"data": out})
}

// NewTab 新建一个标签页。
func NewTab(c *gin.Context) {
	if err := ensureChrome(); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error()}})
		return
	}
	var body struct {
		URL string `json:"url"`
	}
	_ = c.ShouldBindJSON(&body)
	if body.URL == "" {
		body.URL = "about:blank"
	}
	if _, err := newTab(body.URL); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// CloseTab 关闭指定标签页。
// 关不掉的（Chrome 自己的界面页）单独给一个 code，前端据此把这一行从标签条上抹掉——
// 用户按了「关闭」就该看见它消失，哪怕 Chrome 那边根本不肯放手。
func CloseTab(c *gin.Context) {
	err := closeTab(c.Param("id"))
	if errors.Is(err, ErrNotClosable) {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "not_closable", "message": err.Error()}})
		return
	}
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// reply 统一收口：err 非空 → 502，否则 200 ok。
func reply(c *gin.Context, err error) {
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// TabBack / TabForward / TabReload / TabActivate / TabNavigate：作用于指定标签页的导航控制。
func TabBack(c *gin.Context)     { reply(c, tabHistory(c.Param("id"), -1)) }
func TabForward(c *gin.Context)  { reply(c, tabHistory(c.Param("id"), +1)) }
func TabReload(c *gin.Context)   { reply(c, tabReload(c.Param("id"))) }
func TabActivate(c *gin.Context) { reply(c, activateTab(c.Param("id"))) }

func TabNavigate(c *gin.Context) {
	var body struct {
		URL string `json:"url"`
	}
	_ = c.ShouldBindJSON(&body)
	if body.URL == "" {
		reply(c, nil)
		return
	}
	reply(c, tabNavigate(c.Param("id"), body.URL))
}
