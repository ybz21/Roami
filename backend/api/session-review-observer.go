package api

import (
	"context"
	"errors"
	"log"
	"os"
	"sort"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/sessionreview"
)

const (
	reviewProbeInterval = 15 * time.Second
	reviewFreshness     = 35 * time.Second
	reviewIdleWindow    = 30 * time.Second
	reviewProbesPerTick = 4
)

type reviewWorkspace struct {
	version string
	checked time.Time
}

type reviewWorkspaceTable struct {
	mu     sync.RWMutex
	values map[string]reviewWorkspace
}

func (t *reviewWorkspaceTable) set(author string, value reviewWorkspace) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if value.checked.IsZero() {
		delete(t.values, author)
		return
	}
	if t.values == nil {
		t.values = make(map[string]reviewWorkspace)
	}
	t.values[author] = value
}

func (t *reviewWorkspaceTable) get(author string, now time.Time) (string, bool) {
	t.mu.RLock()
	defer t.mu.RUnlock()
	value, ok := t.values[author]
	return value.version, ok && now.Sub(value.checked) <= reviewFreshness
}

type idleReviewProbe struct {
	workspace     reviewWorkspace
	stableSince   time.Time
	idleSince     time.Time
	next          time.Time
	retryDelivery time.Time
	signals       map[string]os.FileInfo
	lastWork      time.Time
}

func (p idleReviewProbe) checkSignals() bool {
	changed := false
	for path, previous := range p.signals {
		current, _ := os.Stat(path)
		if previous == nil && current == nil {
			continue
		}
		if previous == nil || current == nil || !os.SameFile(previous, current) || previous.Size() != current.Size() || previous.ModTime() != current.ModTime() {
			p.signals[path], changed = current, true
		}
	}
	return changed
}

func (a *API) driveSessionReviews(sessions map[string]string, authors, paused map[string]bool, probes map[string]idleReviewProbe, now time.Time) {
	ctx, stop := context.WithTimeout(context.Background(), 3*time.Second)
	defer stop()
	rt := lifecycleRuntime(ctx)
	store := sessionreview.Open(rt)
	active := make(map[string]bool)
	remaining := reviewProbesPerTick
	var pairs []sessionreview.Pair
	store.ForAuthors(authors, func(pair sessionreview.Pair) { pairs = append(pairs, pair) })
	sort.SliceStable(pairs, func(i, j int) bool {
		return probes[pairs[i].Author.Session].lastWork.Before(probes[pairs[j].Author.Session].lastWork)
	})
	drive := func(pair sessionreview.Pair) {
		author, reviewer := pair.Author.Session, pair.Reviewer.Session
		if !pair.Active() {
			return
		}
		active[author] = true
		if ctx.Err() != nil {
			return
		}
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
		ready := func(endpoint sessionreview.Endpoint) bool {
			return observedIdle(endpoint) && reviewPaneReady(rt, endpoint)
		}
		probe := probes[author]
		defer func() { probes[author] = probe }()
		if probe.checkSignals() {
			probe.next = time.Time{}
			a.reviewWorkspaces.set(author, reviewWorkspace{})
		}
		if observedIdle(pair.Author) {
			if probe.idleSince.IsZero() {
				probe.idleSince, probe.next = now, time.Time{}
			}
		} else if !probe.idleSince.IsZero() {
			probe.idleSince, probe.next = time.Time{}, time.Time{}
			a.reviewWorkspaces.set(author, reviewWorkspace{})
		}
		if remaining == 0 {
			return
		}
		observe := func(version string, err error) {
			delay := reviewProbeInterval
			if err != nil {
				probe.workspace, probe.stableSince = reviewWorkspace{}, time.Time{}
				delay = reviewFreshness
			} else {
				if probe.stableSince.IsZero() || probe.workspace.version != version {
					probe.stableSince = now
				}
				probe.workspace = reviewWorkspace{version: version, checked: now}
			}
			probe.next = now.Add(delay)
			a.reviewWorkspaces.set(author, probe.workspace)
		}
		if pair.Pending != nil && !now.Before(probe.retryDelivery) && (pair.Pending.Started || observedIdle(pair.Recipient())) {
			remaining--
			probe.lastWork = now
			if identity, err := rt.SessionIdentity(pair.Recipient().Session); err != nil {
				return
			} else if identity != pair.Recipient().Identity {
				_ = store.Interrupt(ctx, author, "identity_changed")
				return
			}
			if err := store.Deliver(ctx, author, ready, func(endpoint sessionreview.Endpoint, body string) error {
				return rt.SendReviewPrompt(endpoint.Session, endpoint.Pane, body, func() bool {
					identity, err := rt.SessionIdentity(endpoint.Session)
					return err == nil && identity == endpoint.Identity && ready(endpoint)
				})
			}, observe); err != nil {
				probe.retryDelivery = now.Add(reviewFreshness)
				log.Printf("session review %s: %v", author, err)
			}
			return
		}
		if now.Before(probe.next) || (!pair.AutoQueue() && pair.Phase != "reviewing") {
			return
		}
		for _, endpoint := range []sessionreview.Endpoint{pair.Author, pair.Reviewer} {
			identity, err := rt.SessionIdentity(endpoint.Session)
			if err != nil {
				observe("", err)
				return
			}
			if identity != endpoint.Identity {
				_ = store.Interrupt(ctx, author, "identity_changed")
				return
			}
		}
		remaining--
		probe.lastWork = now
		if probe.signals == nil {
			if paths, err := sessionreview.WorkspaceSignalPaths(ctx, pair.Directory); err == nil {
				probe.signals = make(map[string]os.FileInfo, len(paths))
				for _, path := range paths {
					probe.signals[path], _ = os.Stat(path)
				}
			}
		}
		version, err := sessionreview.WorkspaceVersion(ctx, pair)
		observe(version, err)
		if err != nil || version == "" || pair.Reviewed(version) || !pair.AutoQueue() ||
			probe.idleSince.IsZero() || now.Sub(probe.idleSince) < reviewIdleWindow || now.Sub(probe.stableSince) < reviewIdleWindow || !ready(pair.Author) {
			return
		}
		if err = store.QueueIdle(ctx, author, version); err != nil && !errors.Is(err, sessionreview.ErrAlreadyReviewed) && !errors.Is(err, sessionreview.ErrWorkspaceChanged) {
			log.Printf("idle session review %s: %v", author, err)
		}
	}
	for _, pair := range pairs {
		drive(pair)
	}
	for author := range probes {
		if !active[author] {
			delete(probes, author)
			a.reviewWorkspaces.set(author, reviewWorkspace{})
		}
	}
}
