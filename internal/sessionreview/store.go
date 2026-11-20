// Package sessionreview owns ordinary-session review bindings and message receipts.
package sessionreview

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"

	"github.com/ybz21/Roami/internal/id"
	"github.com/ybz21/Roami/internal/sessionlifecycle"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

const MaxRounds = 3

type Endpoint struct {
	Session  string `json:"session"`
	Identity string `json:"identity"`
	Pane     string `json:"pane"`
	Agent    string `json:"agent"`
}

type Pair struct {
	Author      Endpoint `json:"author"`
	Reviewer    Endpoint `json:"reviewer"`
	Directory   string   `json:"directory"`
	Base        string   `json:"base"`
	Trigger     string   `json:"trigger"`
	Phase       string   `json:"phase"`
	Rounds      []Round  `json:"rounds,omitempty"`
	Pending     *Message `json:"pending,omitempty"`
	Interrupted string   `json:"interrupted,omitempty"`
}

type Round struct {
	Version string `json:"version"`
	Request string `json:"request"`
	Result  string `json:"result,omitempty"`
	Verdict string `json:"verdict,omitempty"`
}

type Message struct {
	Kind    string `json:"kind"`
	Round   int    `json:"round"`
	Version string `json:"version"`
	Text    string `json:"text"`
	Started bool   `json:"started,omitempty"`
}

type Status struct {
	Peer  string `json:"peer"`
	Role  string `json:"role"`
	Phase string `json:"phase"`
	Round int    `json:"round,omitempty"`
}

type Store struct {
	root  string
	locks *sessionlifecycle.Store
}

func Open(rt runtime.Runtime) *Store {
	return &Store{
		root:  filepath.Join(rt.DataDir, "session-reviews"),
		locks: &sessionlifecycle.Store{LockDir: filepath.Join(rt.DataDir, "session-reviews", "locks")},
	}
}

func (s *Store) ownerDir(author string) string { return filepath.Join(s.root, author) }

func (s *Store) Load(author string) (Pair, error) {
	var p Pair
	if !id.Valid(author) {
		return p, os.ErrNotExist
	}
	data, err := os.ReadFile(filepath.Join(s.ownerDir(author), "review.json"))
	if err != nil {
		return p, err
	}
	err = json.Unmarshal(data, &p)
	return p, err
}

func (s *Store) save(p Pair) error {
	data, err := json.Marshal(p)
	if err != nil {
		return err
	}
	return replaceFile(s.ownerDir(p.Author.Session), "review.json", func(f *os.File) error {
		_, err := f.Write(data)
		return err
	})
}

func replaceFile(directory, name string, write func(*os.File) error) error {
	if err := os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(directory, ".review-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if err = write(f); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = os.Rename(f.Name(), filepath.Join(directory, name)); err != nil {
		return err
	}
	dir, err := os.Open(directory)
	if err != nil {
		return err
	}
	defer dir.Close()
	return dir.Sync()
}

func (s *Store) Bind(ctx context.Context, p Pair) error {
	if !id.Valid(p.Author.Session) || !id.Valid(p.Reviewer.Session) || p.Author.Session == p.Reviewer.Session {
		return errors.New("invalid review pair")
	}
	release, err := s.locks.Acquire(ctx, p.Author.Session, false)
	if err != nil {
		return err
	}
	defer release()
	current, err := s.Load(p.Author.Session)
	if err == nil {
		if current.Author != p.Author || current.Reviewer != p.Reviewer || current.Trigger != p.Trigger || current.Directory != p.Directory || current.Base != p.Base {
			return errors.New("review pair already bound")
		}
		return nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	p.Phase = "waiting"
	return s.save(p)
}

func (s *Store) Change(ctx context.Context, author string, act func(*Pair) (bool, error)) error {
	if !id.Valid(author) {
		return os.ErrNotExist
	}
	release, err := s.locks.Acquire(ctx, author, false)
	if err != nil {
		return err
	}
	defer release()
	p, err := s.Load(author)
	if err != nil {
		return err
	}
	changed, err := act(&p)
	if err != nil || !changed {
		return err
	}
	return s.save(p)
}

func (p Pair) Active() bool {
	return p.Phase == "waiting" || p.Phase == "reviewing" || p.Phase == "changes"
}

func (p Pair) Statuses(view map[string]Status) {
	round := len(p.Rounds)
	view[p.Author.Session] = Status{Peer: p.Reviewer.Session, Role: "author", Phase: p.Phase, Round: round}
	view[p.Reviewer.Session] = Status{Peer: p.Author.Session, Role: "reviewer", Phase: p.Phase, Round: round}
}

func (s *Store) Interrupt(ctx context.Context, author, reason string) error {
	err := s.Change(ctx, author, func(p *Pair) (bool, error) {
		if !p.Active() {
			return false, nil
		}
		p.Phase, p.Interrupted = "interrupted", reason
		return true, nil
	})
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return err
}

// ForAuthors reads active and historical pairs only for sessions in the caller's view.
func (s *Store) ForAuthors(authors map[string]bool, visit func(Pair)) {
	entries, err := os.ReadDir(s.root)
	if err != nil {
		return
	}
	for _, entry := range entries {
		author := entry.Name()
		if !entry.IsDir() || !authors[author] {
			continue
		}
		p, err := s.Load(author)
		if err == nil {
			visit(p)
		}
	}
}
