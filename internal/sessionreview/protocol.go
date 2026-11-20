package sessionreview

import (
	"context"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/memguard"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

var verdictHeader = regexp.MustCompile(`^r([1-3]) rev=([0-9a-f]{64})[[:space:]]+`)
var paneID = regexp.MustCompile(`^%[0-9]+$`)

func (s *Store) QueueCLI(ctx context.Context, rt runtime.Runtime, target, text string) (bool, error) {
	if !strings.HasPrefix(text, "[review.") {
		return false, nil
	}
	if strings.IndexFunc(text, func(r rune) bool { return r < ' ' && r != '\n' && r != '\t' || r == 127 }) >= 0 {
		return true, errors.New("review messages cannot contain terminal control characters")
	}
	header, body, ok := strings.Cut(text, "]")
	if !ok || strings.TrimSpace(body) == "" {
		return true, errors.New("review message requires a type and text")
	}
	sourcePane := os.Getenv("TMUX_PANE")
	if !paneID.MatchString(sourcePane) {
		return true, errors.New("send review messages from the bound Agent session")
	}
	out, err := rt.TmuxOutput("display-message", "-p", "-t", sourcePane, "#{session_name}\t#{pane_pid}")
	source, root, found := strings.Cut(strings.TrimSpace(out), "\t")
	pid, _ := strconv.Atoi(root)
	if err != nil || !found || !memguard.ProcessDescendsFrom(os.Getpid(), pid) {
		return true, errors.New("cannot verify the source review pane")
	}
	author := source
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	if row, found := meta.Get(source); found && row.CreatedBy == "review" {
		author = row.Parent
	}
	err = s.Change(ctx, author, func(p *Pair) (bool, error) {
		from, to := p.Author, p.Reviewer
		if source == p.Reviewer.Session {
			from, to = p.Reviewer, p.Author
		}
		actual, err := rt.SessionIdentity(source)
		if err != nil || actual != from.Identity || source != from.Session || sourcePane != from.Pane || target != to.Session {
			return false, errors.New("review message does not match the bound sessions")
		}
		if p.Pending != nil {
			return false, errors.New("a review message is already queued")
		}
		body = strings.TrimSpace(body)
		switch header {
		case "[review.request":
			if source != p.Author.Session || (len(p.Rounds) == 0 && p.Trigger == "idle") {
				return false, errors.New("this review request is not expected from the source session")
			}
			return s.queueRequest(ctx, p, body)
		case "[review.changes_requested", "[review.approved":
			if source != p.Reviewer.Session {
				return false, errors.New("only the bound reviewer can submit a verdict")
			}
			return queueVerdict(p, strings.TrimPrefix(header, "[review."), body)
		default:
			return false, errors.New("unknown review message type")
		}
	})
	return true, err
}

func (s *Store) QueueIdle(ctx context.Context, author string) error {
	return s.Change(ctx, author, func(p *Pair) (bool, error) {
		if p.Trigger != "idle" || p.Phase != "waiting" || p.Pending != nil {
			return false, nil
		}
		return s.queueRequest(ctx, p, "The author is idle. Review this workspace snapshot against the original task.")
	})
}

func (s *Store) queueRequest(ctx context.Context, p *Pair, body string) (bool, error) {
	if p.Phase != "waiting" && p.Phase != "changes" || len(p.Rounds) >= MaxRounds {
		return false, errors.New("this review is not accepting a new revision")
	}
	round := len(p.Rounds) + 1
	version, err := s.snapshot(ctx, *p, round)
	if err != nil {
		return false, err
	}
	for _, existing := range p.Rounds {
		if existing.Version == version {
			return false, errors.New("this workspace version was already reviewed")
		}
	}
	p.Pending = &Message{Kind: "request", Round: round, Version: version, Text: body}
	return true, nil
}

func queueVerdict(p *Pair, verdict, body string) (bool, error) {
	if p.Phase != "reviewing" || len(p.Rounds) == 0 {
		return false, errors.New("no review round is awaiting a verdict")
	}
	fields := verdictHeader.FindStringSubmatch(body)
	if fields == nil || fields[1] != strconv.Itoa(len(p.Rounds)) || fields[2] != p.Rounds[len(p.Rounds)-1].Version {
		return false, errors.New("verdict must use the round and full revision from the review request")
	}
	detail := strings.TrimSpace(strings.TrimPrefix(body, fields[0]))
	if detail == "" {
		return false, errors.New("review verdict requires verification details")
	}
	p.Pending = &Message{Kind: verdict, Round: len(p.Rounds), Version: fields[2], Text: detail}
	return true, nil
}

func (p Pair) Recipient() Endpoint {
	if p.Pending != nil && p.Pending.Kind == "request" {
		return p.Reviewer
	}
	return p.Author
}

func (s *Store) Deliver(ctx context.Context, author string, ready func(Endpoint) bool, send func(Endpoint, string) error) error {
	return s.Change(ctx, author, func(p *Pair) (bool, error) {
		m := p.Pending
		if !p.Active() || m == nil {
			return false, nil
		}
		if m.Started {
			p.Phase, p.Interrupted = "interrupted", "delivery_unconfirmed"
			return true, nil
		}
		recipient := p.Recipient()
		if !ready(recipient) {
			return false, nil
		}
		m.Started = true
		if err := s.save(*p); err != nil {
			return false, err
		}
		body := fmt.Sprintf("[review.%s] r%d rev=%s\n\n%s", m.Kind, m.Round, m.Version, m.Text)
		if m.Kind == "request" {
			body += "\n\nBaseline: " + p.Base + "\nRead-only patch: " + s.SnapshotPath(author, m.Round)
		} else if m.Kind == "changes_requested" && m.Round == MaxRounds {
			body += "\n\nReview has reached its round limit. Record any remaining findings and stop the review loop."
		}
		if err := send(recipient, body); err != nil {
			p.Phase, p.Interrupted = "interrupted", "delivery_unconfirmed"
			return true, nil
		}
		if m.Kind == "request" {
			p.Rounds = append(p.Rounds, Round{Version: m.Version, Request: m.Text})
			p.Phase = "reviewing"
		} else {
			round := &p.Rounds[m.Round-1]
			round.Verdict, round.Result = m.Kind, m.Text
			p.Phase = "changes"
			if m.Kind == "approved" {
				p.Phase = "approved"
			} else if m.Round == MaxRounds {
				p.Phase = "limit"
			}
		}
		p.Pending = nil
		return true, nil
	})
}
