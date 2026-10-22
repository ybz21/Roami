// Package browsertabs owns durable tab origins and lifecycle coordination.
package browsertabs

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"time"

	"golang.org/x/sys/unix"
)

type Policy struct {
	MaxTabs           int `json:"maxTabs"`
	SleepAfterSeconds int `json:"sleepAfterSeconds"`
	CloseAfterSeconds int `json:"closeAfterSeconds"`
}
type Policies struct {
	Agent Policy `json:"agent"`
	Human Policy `json:"human"`
}

func Defaults() Policies {
	return Policies{Agent: Policy{MaxTabs: 20, SleepAfterSeconds: 120, CloseAfterSeconds: 600}, Human: Policy{SleepAfterSeconds: 1800}}
}

func (p *Policies) UnmarshalJSON(data []byte) error {
	type plain Policies
	value := plain(Defaults())
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	*p = Policies(value)
	return nil
}

func (p Policies) For(origin string) Policy {
	if origin == "human" {
		return p.Human
	}
	return p.Agent
}
func (p Policies) Valid() bool {
	for _, v := range []Policy{p.Agent, p.Human} {
		if v.MaxTabs < 0 || v.MaxTabs > 1000 {
			return false
		}
		if v.SleepAfterSeconds < 0 || v.CloseAfterSeconds < 0 || v.SleepAfterSeconds > 604800 || v.CloseAfterSeconds > 604800 || (v.SleepAfterSeconds > 0 && v.CloseAfterSeconds > 0 && v.CloseAfterSeconds < v.SleepAfterSeconds) {
			return false
		}
	}
	return true
}
func ReadPolicies(root string) Policies {
	var c struct {
		TabPolicies *Policies `json:"tabPolicies"`
	}
	b, _ := os.ReadFile(filepath.Join(root, "browser-config.json"))
	_ = json.Unmarshal(b, &c)
	if c.TabPolicies != nil && c.TabPolicies.Valid() {
		return *c.TabPolicies
	}
	return Defaults()
}

type Entry struct {
	CreatedBy  string            `json:"createdBy"`
	Origin     string            `json:"origin"`
	Pinned     bool              `json:"pinned"`
	Sleeping   bool              `json:"sleeping"`
	CreatedAt  int64             `json:"createdAt"`
	LastUsedAt int64             `json:"lastUsedAt"`
	Busy       map[string]string `json:"busy,omitempty"`
}
type Event struct {
	CreatedBy  string   `json:"createdBy,omitempty"`
	LastUsedAt *int64   `json:"lastUsedAt,omitempty"`
	Action     string   `json:"action"`
	BrowserID  string   `json:"browserId"`
	TargetID   string   `json:"targetId"`
	Targets    []string `json:"targets"`
	Origin     string   `json:"origin"`
	Pinned     *bool    `json:"pinned"`
	Token      string   `json:"token"`
	Known      bool     `json:"known"`
	Sleeping   bool     `json:"sleeping"`
}
type Result struct {
	Entries  map[string]Entry `json:"entries"`
	Policies Policies         `json:"policies"`
}

var identifier = regexp.MustCompile(`^[A-Za-z0-9_-]{1,128}$`)
var ErrBusy = errors.New("BROWSER_TAB_BUSY")
var ErrInvalid = errors.New("INVALID_BROWSER_TAB_METADATA")

func Apply(root string, e Event) (Result, error) {
	result := Result{Policies: ReadPolicies(root)}
	if !identifier.MatchString(e.BrowserID) || (e.Origin != "" && e.Origin != "human" && e.Origin != "agent") {
		return result, ErrInvalid
	}
	if e.Action != "sync" && !identifier.MatchString(e.TargetID) {
		return result, ErrInvalid
	}
	if err := os.MkdirAll(root, 0700); err != nil {
		return result, err
	}
	lock, err := os.OpenFile(filepath.Join(root, "browser-tabs.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return result, err
	}
	defer lock.Close()
	if err = unix.Flock(int(lock.Fd()), unix.LOCK_EX); err != nil {
		return result, err
	}
	defer unix.Flock(int(lock.Fd()), unix.LOCK_UN)
	path := filepath.Join(root, "browser-tabs.json")
	catalog := map[string]map[string]Entry{}
	b, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return result, err
	}
	if len(b) > 0 {
		if err = json.Unmarshal(b, &catalog); err != nil {
			return result, err
		}
	}
	entries := catalog[e.BrowserID]
	if entries == nil {
		entries = map[string]Entry{}
		catalog[e.BrowserID] = entries
	}
	now := time.Now().UnixMilli()
	changed := false
	ensure := func(id string) Entry {
		v, ok := entries[id]
		if !ok {
			v = Entry{CreatedBy: "agent", Origin: "agent", CreatedAt: now, LastUsedAt: now}
			entries[id] = v
			changed = true
		}
		if v.CreatedBy == "" {
			v.CreatedBy = "agent"
			entries[id] = v
			changed = true
		}
		return v
	}
	if e.Action == "sync" {
		live := map[string]bool{}
		for _, id := range e.Targets {
			if !identifier.MatchString(id) {
				return result, ErrInvalid
			}
			live[id] = true
			ensure(id)
		}
		for id := range entries {
			if !live[id] && entries[id].LastUsedAt < now-3600000 {
				delete(entries, id)
				changed = true
			}
		}
	} else {
		v := ensure(e.TargetID)
		switch e.Action {
		case "create", "update", "restore":
			for _, kind := range v.Busy {
				if kind == "maintenance" {
					return result, ErrBusy
				}
			}
			if e.Origin != "" {
				v.Origin = e.Origin
			}
			if e.Action == "create" {
				v.CreatedBy = v.Origin
			}
			if e.Action == "restore" {
				if e.CreatedBy != "agent" && e.CreatedBy != "human" {
					return result, ErrInvalid
				}
				v.CreatedBy = e.CreatedBy
			}
			if e.Pinned != nil {
				v.Pinned = *e.Pinned
			}
			v.LastUsedAt = max(now, v.LastUsedAt+1)
		case "touch":
			for _, kind := range v.Busy {
				if kind == "maintenance" {
					return result, ErrBusy
				}
			}
			v.LastUsedAt = max(now, v.LastUsedAt+1)
			v.Sleeping = false
		case "start", "maintain":
			if !identifier.MatchString(e.Token) {
				return result, ErrInvalid
			}
			for _, kind := range v.Busy {
				if kind == "maintenance" {
					return result, ErrBusy
				}
			}
			if e.Action == "maintain" && (e.Origin != v.Origin || v.Pinned || len(v.Busy) > 0 || (e.LastUsedAt != nil && *e.LastUsedAt != v.LastUsedAt)) {
				return result, ErrBusy
			}
			if len(v.Busy) >= 64 {
				return result, ErrBusy
			}
			if v.Busy == nil {
				v.Busy = map[string]string{}
			}
			v.Busy[e.Token] = e.Action
			if e.Action == "maintain" {
				v.Busy[e.Token] = "maintenance"
			} else {
				v.LastUsedAt = max(now, v.LastUsedAt+1)
			}
		case "finish":
			if e.Known {
				kind, exists := v.Busy[e.Token]
				if !exists {
					break
				}
				delete(v.Busy, e.Token)
				if kind == "maintenance" {
					if e.Sleeping {
						v.Sleeping = true
					}
				} else {
					v.Sleeping = false
					v.LastUsedAt = max(now, v.LastUsedAt+1)
				}
			}
		default:
			return result, ErrInvalid
		}
		entries[e.TargetID] = v
		changed = true
	}
	if changed {
		b, err = json.Marshal(catalog)
		if err != nil {
			return result, err
		}
		if len(b) > 4<<20 {
			return result, errors.New("BROWSER_TAB_CATALOG_FULL")
		}
		f, err := os.CreateTemp(root, ".browser-tabs-*")
		if err != nil {
			return result, err
		}
		defer os.Remove(f.Name())
		if err = f.Chmod(0600); err == nil {
			_, err = f.Write(b)
		}
		if err == nil {
			err = f.Sync()
		}
		closeErr := f.Close()
		if err == nil {
			err = closeErr
		}
		if err != nil {
			return result, err
		}
		if err = os.Rename(f.Name(), path); err != nil {
			return result, err
		}
	}
	result.Entries = entries
	return result, nil
}

// CreationLock serializes CLI and API creation before checking shared capacity.
func CreationLock(root string) (func(), error) {
	if err := os.MkdirAll(root, 0700); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(root, "browser-tabs-create.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = unix.Flock(int(f.Fd()), unix.LOCK_EX); err != nil {
		f.Close()
		return nil, err
	}
	return func() { _ = unix.Flock(int(f.Fd()), unix.LOCK_UN); _ = f.Close() }, nil
}
