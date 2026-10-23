package api

import (
	"errors"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

var notificationResponseLocks sync.Map

var errPromptChanged = errors.New("prompt changed")

func respondToNotification(token, choice string, capture func() (string, error), send func(...string) error) error {
	screen, err := capture()
	if err != nil {
		return err
	}
	p, ok := notificationPromptFromScreen(screen)
	if !ok || p.token() != token || p.Multiple {
		return errPromptChanged
	}
	if p.YesNo {
		var key string
		switch choice {
		case "yes":
			key = "y"
		case "no":
			key = "n"
		default:
			return errPromptChanged
		}
		if err = send(key); err != nil {
			return err
		}
		time.Sleep(250 * time.Millisecond)
		screen, err = capture()
		if err != nil {
			return err
		}
		after, stillWaiting := notificationPromptFromScreen(screen)
		if stillWaiting && after.token() == token {
			return send("Enter")
		}
		return nil
	}
	n, err := strconv.Atoi(choice)
	if err != nil || n < 1 || n > len(p.Choices) {
		return errPromptChanged
	}
	if p.Selected < 0 {
		if !p.Numbered {
			return errPromptChanged
		}
		if err = send(choice); err != nil {
			return err
		}
	} else {
		var keys []string
		for step := p.Selected; step < n-1; step++ {
			keys = append(keys, "Down")
		}
		for step := p.Selected; step > n-1; step-- {
			keys = append(keys, "Up")
		}
		if len(keys) > 0 {
			if err = send(keys...); err != nil {
				return err
			}
		}
	}
	time.Sleep(250 * time.Millisecond)
	screen, err = capture()
	if err != nil {
		return err
	}
	after, ok := notificationPromptFromScreen(screen)
	// Some TUIs submit on a number key; never send Enter into the next question.
	if !ok || after.token() != token {
		if p.Selected >= 0 {
			return errPromptChanged
		}
		return nil
	}
	if after.Selected != n-1 {
		return errPromptChanged
	}
	return send("Enter")
}

func (a *API) NotificationResponse(c *gin.Context) {
	name := a.sessionTarget(c)
	var b struct {
		Prompt string `json:"prompt"`
		Choice string `json:"choice"`
	}
	if c.ShouldBindJSON(&b) != nil || b.Prompt == "" || b.Choice == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	entry, _ := notificationResponseLocks.LoadOrStore(name, &sync.Mutex{})
	lock := entry.(*sync.Mutex)
	lock.Lock()
	defer lock.Unlock()
	err := respondToNotification(b.Prompt, b.Choice, func() (string, error) { return a.TT.Run("capture-pane", "-t", "="+name+":", "-p", "-J", "-S", "-60") }, func(keys ...string) error {
		args := append([]string{"send-keys", "-t", "=" + name + ":"}, keys...)
		_, err := a.TT.Run(args...)
		return err
	})
	if errors.Is(err, errPromptChanged) {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "PROMPT_CHANGED"}})
		return
	}
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"code": "TMUX_ERROR"}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}
