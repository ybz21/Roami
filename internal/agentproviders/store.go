package agentproviders

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"

	"golang.org/x/sys/unix"
)

type Store struct {
	root string
	mu   sync.Mutex
}

func NewStore(dataRoot string) *Store {
	return &Store{root: filepath.Join(dataRoot, "agents", "professional")}
}

func (s *Store) locked(run func(*catalog) error) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := os.MkdirAll(s.root, 0700); err != nil {
		return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
	}
	file, err := os.OpenFile(filepath.Join(s.root, "presets.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
	}
	defer file.Close()
	if unix.Flock(int(file.Fd()), unix.LOCK_EX) != nil {
		return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
	}
	defer unix.Flock(int(file.Fd()), unix.LOCK_UN)
	state := &catalog{Kinds: map[string]*kindState{}}
	data, err := os.ReadFile(filepath.Join(s.root, "provider-presets.json"))
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("MODEL_STORE_READ_FAILED")
	}
	if err == nil && (len(data) > maxFileSize || json.Unmarshal(data, state) != nil || state.Kinds == nil) {
		return fmt.Errorf("MODEL_STORE_READ_FAILED")
	}
	if err := s.recoverPending(state); err != nil {
		return err
	}
	return run(state)
}

func (s *Store) save(state *catalog) error {
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil || len(data) > maxFileSize {
		return fmt.Errorf("MODEL_STORE_TOO_LARGE")
	}
	if writePrivate(filepath.Join(s.root, "provider-presets.json"), data) != nil {
		return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
	}
	return nil
}

func stateFor(state *catalog, kind string) *kindState {
	if state.Kinds[kind] == nil {
		state.Kinds[kind] = &kindState{Profiles: []Profile{}}
	}
	return state.Kinds[kind]
}

func makeView(kind string, state *kindState, config nativeConfig) (View, error) {
	view := View{Profiles: []ProfileSummary{}, Current: config.current(kind), Revision: config.revision(), ConfigPaths: configPaths(config), OpenCodeMajor: config.Major}
	samePaths := reflect.DeepEqual(state.Paths, configPaths(config))
	view.CanRestore = len(state.Original) > 0 && samePaths
	var active bool
	if state.ActiveID != "" && samePaths {
		current, err := config.capture(state.AppliedFields)
		if err != nil {
			return View{}, err
		}
		active = digest(current) == state.NativeDigest
		if active {
			view.ActiveID = state.ActiveID
		}
	}
	view.Changed = state.ActiveID != "" && !active
	for _, p := range state.Profiles {
		view.Profiles = append(view.Profiles, ProfileSummary{ID: p.ID, Name: p.Name, BaseURL: p.BaseURL, Model: p.Model, Protocol: p.Protocol,
			AuthMode: p.AuthMode, KeyEnv: p.KeyEnv, ReasoningEffort: p.ReasoningEffort, HasKey: p.APIKey != "",
			Applied: active && state.ActiveID == p.ID && digest(p) == state.ProfileDigest})
		if view.Current.Provider == providerID(p) || (kind == "claude" && active && p.ID == state.ActiveID) {
			view.Current.Provider = p.Name
		}
	}
	return view, nil
}

func (s *Store) View(ctx context.Context, kind string) (View, error) {
	if err := validateKind(kind); err != nil {
		return View{}, err
	}
	var view View
	err := s.locked(func(state *catalog) error {
		config, err := loadNative(ctx, kind)
		if err != nil {
			return err
		}
		view, err = makeView(kind, stateFor(state, kind), config)
		return err
	})
	return view, err
}

// Observations reuse the applied fields; status polling does not start another CLI.
func (s *Store) Observations(ctx context.Context) map[string]string {
	result := map[string]string{}
	_ = s.locked(func(state *catalog) error {
		for kind, current := range state.Kinds {
			if current == nil || current.ActiveID == "" || validateKind(kind) != nil {
				continue
			}
			config, err := readNative(ctx, kind, false)
			if err != nil {
				continue
			}
			view, err := makeView(kind, current, config)
			if err != nil || view.ActiveID == "" {
				continue
			}
			for _, profile := range current.Profiles {
				if profile.ID == view.ActiveID {
					result[kind] = profile.Name
				}
			}
		}
		return nil
	})
	return result
}

func (s *Store) Save(ctx context.Context, kind, profileID string, input ProfileInput) (ProfileSummary, error) {
	if err := validateKind(kind); err != nil {
		return ProfileSummary{}, err
	}
	var result ProfileSummary
	err := s.locked(func(state *catalog) error {
		if err := ctx.Err(); err != nil {
			return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
		}
		current := stateFor(state, kind)
		var previous *Profile
		index := -1
		if profileID != "" {
			if !validID.MatchString(profileID) {
				return fmt.Errorf("MODEL_PROFILE_NOT_FOUND")
			}
			for i := range current.Profiles {
				if current.Profiles[i].ID == profileID {
					index, previous = i, &current.Profiles[i]
					break
				}
			}
			if index < 0 {
				return fmt.Errorf("MODEL_PROFILE_NOT_FOUND")
			}
		} else {
			if len(current.Profiles) >= 32 {
				return fmt.Errorf("MODEL_PROFILE_LIMIT")
			}
			var err error
			profileID, err = newID()
			if err != nil {
				return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
			}
		}
		p, err := profileFromInput(kind, profileID, input, previous)
		if err != nil {
			return err
		}
		for _, existing := range current.Profiles {
			if existing.ID != p.ID && strings.EqualFold(existing.Name, p.Name) {
				return fmt.Errorf("MODEL_PROFILE_NAME_EXISTS")
			}
		}
		if index >= 0 {
			current.Profiles[index] = p
		} else {
			current.Profiles = append(current.Profiles, p)
		}
		if err := s.save(state); err != nil {
			return err
		}
		result = ProfileSummary{ID: p.ID, Name: p.Name, BaseURL: p.BaseURL, Model: p.Model, Protocol: p.Protocol, AuthMode: p.AuthMode,
			KeyEnv: p.KeyEnv, HasKey: p.APIKey != "", ReasoningEffort: p.ReasoningEffort}
		return nil
	})
	return result, err
}

func (s *Store) Delete(ctx context.Context, kind, profileID string) error {
	if err := validateKind(kind); err != nil {
		return err
	}
	return s.locked(func(state *catalog) error {
		current := stateFor(state, kind)
		config, err := loadNative(ctx, kind)
		if err != nil {
			return err
		}
		view, err := makeView(kind, current, config)
		if err != nil {
			return err
		}
		if view.ActiveID == profileID {
			return fmt.Errorf("MODEL_PROFILE_ACTIVE")
		}
		for i, p := range current.Profiles {
			if p.ID == profileID {
				current.Profiles = append(current.Profiles[:i], current.Profiles[i+1:]...)
				return s.save(state)
			}
		}
		return fmt.Errorf("MODEL_PROFILE_NOT_FOUND")
	})
}
