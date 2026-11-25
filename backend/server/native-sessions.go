package server

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/pty"
	"github.com/ybz21/Roami/internal/sessionbackend"
)

// mountNativeTerminal exposes the opt-in native session REST + WebSocket endpoints when
// Config.NativeSessionBackend is configured (default stays 100% tmux when nil).
func mountNativeTerminal(g *gin.RouterGroup, b sessionbackend.SessionBackend) {
	if b == nil {
		return
	}
	g.GET("/term/native/:name", pty.NativeHandler(b))

	g.GET("/native-sessions", func(c *gin.Context) {
		rows, err := b.List(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"sessions": rows, "capabilities": b.Capabilities()})
	})

	g.POST("/native-sessions", func(c *gin.Context) {
		var spec sessionbackend.CreateSpec
		if err := c.ShouldBindJSON(&spec); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		ref, err := b.Create(c.Request.Context(), spec)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, ref)
	})

	g.GET("/native-sessions/:id", func(c *gin.Context) {
		st, err := b.Observe(c.Request.Context(), c.Param("id"))
		if err != nil {
			c.JSON(http.StatusNotFound, gin.H{"error": err.Error(), "state": st})
			return
		}
		c.JSON(http.StatusOK, st)
	})

	g.DELETE("/native-sessions/:id", func(c *gin.Context) {
		if err := b.Close(c.Request.Context(), c.Param("id")); err != nil {
			c.JSON(http.StatusNotFound, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	g.POST("/native-sessions/:id/split", func(c *gin.Context) {
		lb, ok := b.(sessionbackend.LayoutBackend)
		if !ok {
			c.JSON(http.StatusNotImplemented, gin.H{"error": "splits unsupported"})
			return
		}
		var req struct {
			PaneID string                  `json:"paneId"`
			Dir    sessionbackend.SplitDir `json:"dir"`
			Ratio  float64                 `json:"ratio"`
			Cwd    string                  `json:"cwd"`
		}
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		win, paneID, err := lb.SplitPane(c.Request.Context(), c.Param("id"), req.PaneID, sessionbackend.SplitSpec{
			Dir: req.Dir, Ratio: req.Ratio, Cwd: req.Cwd,
		})
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"window": win, "paneId": paneID})
	})

	g.POST("/native-sessions/:id/resize-split", func(c *gin.Context) {
		lb, ok := b.(sessionbackend.LayoutBackend)
		if !ok {
			c.JSON(http.StatusNotImplemented, gin.H{"error": "splits unsupported"})
			return
		}
		var req struct {
			WindowID        string  `json:"windowId"`
			NodeID          string  `json:"nodeId"`
			Ratio           float64 `json:"ratio"`
			ExpectedVersion int64   `json:"expectedVersion"`
		}
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		win, err := lb.ResizeSplit(c.Request.Context(), c.Param("id"), req.WindowID, req.NodeID, req.Ratio, req.ExpectedVersion)
		if err != nil {
			c.JSON(http.StatusConflict, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"window": win})
	})

	g.POST("/native-sessions/:id/close-pane", func(c *gin.Context) {
		lb, ok := b.(sessionbackend.LayoutBackend)
		if !ok {
			c.JSON(http.StatusNotImplemented, gin.H{"error": "splits unsupported"})
			return
		}
		var req struct {
			PaneID string `json:"paneId"`
		}
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		win, err := lb.ClosePane(c.Request.Context(), c.Param("id"), req.PaneID)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"window": win})
	})
}
