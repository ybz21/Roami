package api

import (
	"context"
	"crypto/sha256"
	"errors"
	"log"
	"time"

	"github.com/ybz21/Roami/internal/sessionreview"
)

type idleReviewProbe struct {
	screen [32]byte
	since  time.Time
	next   time.Time
}

func (a *API) driveSessionReviews(sessions map[string]string, authors, paused map[string]bool, capture func(string) string, probes map[string]idleReviewProbe, now time.Time) {
	ctx, stop := context.WithTimeout(context.Background(), 3*time.Second)
	defer stop()
	rt := lifecycleRuntime(ctx)
	store := sessionreview.Open(rt)
	active := make(map[string]bool)
	store.ForAuthors(authors, func(pair sessionreview.Pair) {
		if !pair.Active() || ctx.Err() != nil {
			return
		}
		author, reviewer := pair.Author.Session, pair.Reviewer.Session
		if sessions[author] == "" || sessions[reviewer] == "" {
			if err := store.Interrupt(ctx, author, "session_unavailable"); err != nil {
				log.Printf("session review %s: %v", author, err)
			}
			return
		}
		observedIdle := func(endpoint sessionreview.Endpoint) bool {
			snap, ok := a.Live.get(endpoint.Session)
			return ok && snap.Agent == endpoint.Agent && !snap.Busy && !snap.Waiting && !paused[endpoint.Session]
		}
		if pair.Pending != nil {
			target := pair.Recipient()
			if identity, err := rt.SessionIdentity(target.Session); err != nil {
				return
			} else if identity != target.Identity {
				_ = store.Interrupt(ctx, author, "identity_changed")
				return
			}
			ready := func(endpoint sessionreview.Endpoint) bool {
				return observedIdle(endpoint) && reviewPaneReady(rt, endpoint)
			}
			if err := store.Deliver(ctx, author, ready, func(endpoint sessionreview.Endpoint, body string) error {
				return rt.SendReviewPrompt(endpoint.Session, endpoint.Pane, body, func() bool {
					identity, err := rt.SessionIdentity(endpoint.Session)
					return err == nil && identity == endpoint.Identity && ready(endpoint)
				})
			}); err != nil {
				log.Printf("session review %s: %v", author, err)
			}
			return
		}
		if pair.Trigger != "idle" || pair.Phase != "waiting" || !observedIdle(pair.Author) {
			return
		}
		screen := capture(author)
		if screen == "" {
			return
		}
		active[author] = true
		digest := sha256.Sum256([]byte(screen))
		probe := probes[author]
		if probe.screen != digest {
			probes[author] = idleReviewProbe{screen: digest, since: now}
			return
		}
		if now.Sub(probe.since) < 30*time.Second || now.Before(probe.next) {
			return
		}
		probe.next = now.Add(30 * time.Second)
		probes[author] = probe
		identity, err := rt.SessionIdentity(author)
		if err != nil {
			return
		}
		if identity != pair.Author.Identity {
			_ = store.Interrupt(ctx, author, "identity_changed")
			return
		}
		if err = store.QueueIdle(ctx, author); err != nil && !errors.Is(err, sessionreview.ErrNoChanges) {
			log.Printf("idle session review %s: %v", author, err)
		}
	})
	for author := range probes {
		if !active[author] {
			delete(probes, author)
		}
	}
}
