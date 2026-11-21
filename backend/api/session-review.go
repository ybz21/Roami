package api

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/sessionreview"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

var errReviewSessionChanged = errors.New("review session binding changed")

func sessionReviewPair(rt runtime.Runtime, store *sessionreview.Store, name string) (sessionreview.Pair, error) {
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	owner := name
	if row, ok := meta.Get(name); ok && row.CreatedBy == "review" {
		owner = row.Parent
	}
	pair, err := store.Load(owner)
	if err == nil && name != pair.Author.Session && name != pair.Reviewer.Session {
		err = errReviewSessionChanged
	}
	return pair, err
}

func (a *API) SessionReviewHistory(c *gin.Context) {
	rt := lifecycleRuntime(c.Request.Context())
	pair, err := sessionReviewPair(rt, sessionreview.Open(rt), c.Param("name"))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "SESSION_REVIEW_NOT_FOUND"}})
		return
	}
	type verdict struct {
		Round   int    `json:"round"`
		Version string `json:"version"`
		Verdict string `json:"verdict"`
		Result  string `json:"result"`
	}
	rows := make([]verdict, 0, len(pair.Rounds))
	for i, round := range pair.Rounds {
		if round.Verdict != "" {
			rows = append(rows, verdict{i + 1, round.Version, round.Verdict, round.Result})
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"rounds": rows}})
}

func (a *API) ContinueSessionReview(c *gin.Context) {
	var input struct {
		Round int `json:"round" binding:"required,min=1"`
	}
	if c.ShouldBindJSON(&input) != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "SESSION_REVIEW_ROUND_REQUIRED"}})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
	defer cancel()
	rt := lifecycleRuntime(ctx)
	store := sessionreview.Open(rt)
	pair, err := sessionReviewPair(rt, store, c.Param("name"))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "SESSION_REVIEW_NOT_FOUND"}})
		return
	}
	if err := store.Continue(ctx, pair.Author.Session, input.Round, func(pair sessionreview.Pair) error {
		for _, endpoint := range []sessionreview.Endpoint{pair.Author, pair.Reviewer} {
			identity, err := rt.SessionIdentity(endpoint.Session)
			if err != nil || identity != endpoint.Identity {
				return errReviewSessionChanged
			}
		}
		return nil
	}); err != nil {
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "SESSION_REVIEW_CONTINUE_FAILED"}})
		return
	}
	c.Status(http.StatusNoContent)
}
