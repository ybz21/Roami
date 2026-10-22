// tabs.go：标签页管理的 REST 接口（全程复用同一台全局 Chrome）。
//
//	GET    /api/browser/tabs        列出标签页
//	POST   /api/browser/tabs        新建标签页（body 可选 {"url": "..."}）
//	DELETE /api/browser/tabs/:id    关闭标签页
package browser

import (
	"errors"
	"github.com/ybz21/Roami/internal/browsertabs"
	"net/http"
	"path/filepath"

	"github.com/gin-gonic/gin"
)

// Tabs 列出当前所有 page 标签页。
func Tabs(c *gin.Context) {
	if err := ensureBrowserInstance(c.Query("expectedBrowser")); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error()}})
		return
	}
	pages := listPages()
	identity, err := currentBrowserIdentity()
	if err != nil {
		reply(c, err)
		return
	}
	ids := make([]string, 0, len(pages))
	for _, page := range pages {
		ids = append(ids, page.ID)
	}
	catalog, err := tabCatalog(browsertabs.Event{Action: "sync", BrowserID: identity, Targets: ids})
	if err != nil {
		reply(c, err)
		return
	}
	out := make([]gin.H, 0, len(pages))
	for _, t := range pages {
		meta := catalog.Entries[t.ID]
		out = append(out, gin.H{"id": t.ID, "title": t.Title, "url": t.URL, "origin": meta.Origin, "createdBy": meta.CreatedBy, "pinned": meta.Pinned, "sleeping": meta.Sleeping})
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
		URL    string `json:"url"`
		Origin string `json:"origin"`
	}
	if err := c.ShouldBindJSON(&body); err != nil && c.Request.ContentLength > 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	if body.Origin != "" && body.Origin != "human" && body.Origin != "agent" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "INVALID_BROWSER_TAB_METADATA"}})
		return
	}
	if body.URL == "" {
		body.URL = "about:blank"
	}
	cfgStore.mu.Lock()
	file := cfgStore.file
	cfgStore.mu.Unlock()
	release, err := browsertabs.CreationLock(filepath.Dir(file))
	if err != nil {
		reply(c, err)
		return
	}
	defer release()
	if body.Origin != "human" {
		identity, err := currentBrowserIdentity()
		if err != nil {
			reply(c, err)
			return
		}
		pages := listPages()
		ids := make([]string, 0, len(pages))
		for _, p := range pages {
			ids = append(ids, p.ID)
		}
		catalog, err := tabCatalog(browsertabs.Event{Action: "sync", BrowserID: identity, Targets: ids})
		if err != nil {
			reply(c, err)
			return
		}
		count := 0
		for _, id := range ids {
			if catalog.Entries[id].Origin != "human" {
				count++
			}
		}
		if count >= 20 {
			c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "BROWSER_TAB_BUDGET_EXCEEDED"}})
			return
		}
	}
	id, err := newTab("about:blank")
	if err == nil {
		identity, identityErr := currentBrowserIdentity()
		err = identityErr
		if err == nil {
			_, err = tabCatalog(browsertabs.Event{Action: "create", BrowserID: identity, TargetID: id, Origin: body.Origin})
		}
		if err != nil {
			_ = closeTab(id)
		} else if body.URL != "about:blank" {
			err = tabNavigate(id, body.URL)
		}
	}
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error()}})
		return
	}
	if err := activateTab(id); err != nil {
		reply(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true, "id": id}})
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
func TabBack(c *gin.Context)    { reply(c, tabHistory(c.Param("id"), -1)) }
func TabForward(c *gin.Context) { reply(c, tabHistory(c.Param("id"), +1)) }
func TabReload(c *gin.Context)  { reply(c, tabReload(c.Param("id"))) }
func TabActivate(c *gin.Context) {
	id := c.Param("id")
	err := wakeTab(id)
	if err == nil {
		err = activateTab(id)
	}
	reply(c, err)
}

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

func tabCatalog(e browsertabs.Event) (browsertabs.Result, error) {
	cfgStore.mu.Lock()
	file := cfgStore.file
	cfgStore.mu.Unlock()
	if file == "" {
		return browsertabs.Result{}, browsertabs.ErrInvalid
	}
	return browsertabs.Apply(filepath.Dir(file), e)
}

func UpdateTab(c *gin.Context) {
	var in struct {
		Origin string `json:"origin"`
		Pinned *bool  `json:"pinned"`
	}
	if c.ShouldBindJSON(&in) != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	id := c.Param("id")
	if !targetExists(id) {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "CHROME_TARGET_NOT_FOUND"}})
		return
	}
	if in.Origin == "agent" {
		cfgStore.mu.Lock()
		file := cfgStore.file
		cfgStore.mu.Unlock()
		release, err := browsertabs.CreationLock(filepath.Dir(file))
		if err != nil {
			reply(c, err)
			return
		}
		defer release()
		identity, err := currentBrowserIdentity()
		if err != nil {
			reply(c, err)
			return
		}
		pages := listPages()
		ids := make([]string, 0, len(pages))
		for _, p := range pages {
			ids = append(ids, p.ID)
		}
		catalog, err := tabCatalog(browsertabs.Event{Action: "sync", BrowserID: identity, Targets: ids})
		if err != nil {
			reply(c, err)
			return
		}
		count := 0
		for _, target := range ids {
			if catalog.Entries[target].Origin == "agent" {
				count++
			}
		}
		if catalog.Entries[id].Origin != "agent" && count >= 20 {
			c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "BROWSER_TAB_BUDGET_EXCEEDED"}})
			return
		}
	}
	browser, err := currentBrowserIdentity()
	if err == nil {
		_, err = tabCatalog(browsertabs.Event{Action: "update", BrowserID: browser, TargetID: id, Origin: in.Origin, Pinned: in.Pinned})
	}
	if err != nil {
		code := "INVALID_BROWSER_TAB_METADATA"
		if errors.Is(err, browsertabs.ErrBusy) {
			code = "BROWSER_TAB_BUSY"
		}
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": code}})
		return
	}
	rememberRecoveryURLs(pageURLs(listPages()))
	reply(c, nil)
}

func wakeTab(id string) error {
	return withTab(id, func(c *cdp) error {
		_, err := c.call("Page.setWebLifecycleState", map[string]any{"state": "active"})
		return err
	})
}
