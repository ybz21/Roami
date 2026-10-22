package agentproviders

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"
)

type applyJournal struct {
	ID     string     `json:"id"`
	Before []document `json:"before"`
	After  []document `json:"after"`
}

func (s *Store) Apply(ctx context.Context, kind, profileID, revision string) (View, error) {
	return s.apply(ctx, kind, profileID, revision, false)
}

func (s *Store) Restore(ctx context.Context, kind, revision string) (View, error) {
	return s.apply(ctx, kind, "", revision, true)
}

func (s *Store) apply(ctx context.Context, kind, profileID, revision string, restore bool) (View, error) {
	if err := validateKind(kind); err != nil {
		return View{}, err
	}
	var result View
	err := s.locked(func(state *catalog) error {
		current := stateFor(state, kind)
		config, err := loadNative(ctx, kind)
		if err != nil {
			return err
		}
		if revision == "" || revision != config.revision() {
			return fmt.Errorf("AGENT_CONFIG_CHANGED")
		}
		var fields []field
		var selected *Profile
		if restore {
			if len(current.Original) == 0 || !reflect.DeepEqual(current.Paths, configPaths(config)) {
				return fmt.Errorf("AGENT_CONFIG_RESTORE_UNAVAILABLE")
			}
			fields = current.Original
		} else {
			for i := range current.Profiles {
				if current.Profiles[i].ID == profileID {
					selected = &current.Profiles[i]
				}
			}
			if selected == nil {
				return fmt.Errorf("MODEL_PROFILE_NOT_FOUND")
			}
			fields, err = profileFields(kind, *selected, config.Major)
			if err != nil {
				return err
			}
			if len(current.Original) == 0 || !reflect.DeepEqual(current.Paths, configPaths(config)) {
				current.Original, err = config.capture(defaultFields(kind))
				if err != nil {
					return err
				}
				current.Paths = configPaths(config)
			}
		}
		after, err := config.render(fields)
		if err != nil {
			return err
		}
		if ctx.Err() != nil {
			return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
		}
		operation, err := newID()
		if err != nil {
			return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
		}
		journal := applyJournal{ID: operation, Before: config.Documents, After: after.Documents}
		encoded := jsonValue(journal)
		backup := filepath.Join(s.root, "backups", operation+".json")
		if writePrivate(backup, encoded) != nil || writePrivate(filepath.Join(s.root, "pending-apply.json"), encoded) != nil {
			return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
		}
		rollback := func(cause string) error {
			if err := s.recoverPending(state); err != nil {
				return err
			}
			return fmt.Errorf("%s", cause)
		}
		for i, doc := range after.Documents {
			if digest(doc) == digest(config.Documents[i]) {
				continue
			}
			before, readErr := readDocument(config.Documents[i])
			if readErr != nil || digest(before) != digest(config.Documents[i]) {
				return rollback("AGENT_CONFIG_CHANGED")
			}
			if writePrivate(doc.Path, doc.Data) != nil {
				return rollback("AGENT_CONFIG_WRITE_FAILED")
			}
		}
		if restore {
			current.ActiveID, current.ProfileDigest, current.NativeDigest = "", "", ""
			current.AppliedFields = nil
		} else {
			current.ActiveID, current.ProfileDigest = selected.ID, digest(selected)
			current.AppliedFields = fields
			captured, captureErr := after.capture(fields)
			if captureErr != nil {
				return rollback("AGENT_CONFIG_INVALID")
			}
			current.NativeDigest = digest(captured)
		}
		previousOperation := state.LastOperation
		state.LastOperation = operation
		if err := s.save(state); err != nil {
			state.LastOperation = previousOperation
			return rollback("MODEL_STORE_WRITE_FAILED")
		}
		_ = os.Remove(filepath.Join(s.root, "pending-apply.json"))
		s.trimBackups()
		result, err = makeView(kind, current, after)
		return err
	})
	return result, err
}

func (s *Store) recoverPending(state *catalog) error {
	path := filepath.Join(s.root, "pending-apply.json")
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil
	}
	var journal applyJournal
	if err != nil || len(data) > 6*maxFileSize || json.Unmarshal(data, &journal) != nil || !validID.MatchString(journal.ID) ||
		len(journal.Before) != len(journal.After) || len(journal.Before) == 0 || len(journal.Before) > 2 {
		return fmt.Errorf("AGENT_CONFIG_RECOVERY_REQUIRED")
	}
	if state.LastOperation == journal.ID {
		if os.Remove(path) != nil {
			return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
		}
		return nil
	}
	for i := len(journal.Before) - 1; i >= 0; i-- {
		before, after := journal.Before[i], journal.After[i]
		if !filepath.IsAbs(before.Path) || before.Path != after.Path {
			return fmt.Errorf("AGENT_CONFIG_RECOVERY_REQUIRED")
		}
		current, readErr := readDocument(before)
		if readErr != nil {
			return fmt.Errorf("AGENT_CONFIG_RECOVERY_REQUIRED")
		}
		if digest(current) == digest(before) {
			continue
		}
		if digest(current) != digest(after) {
			return fmt.Errorf("AGENT_CONFIG_RECOVERY_REQUIRED")
		}
		if before.Exists {
			err = writePrivate(before.Path, before.Data)
		} else {
			err = os.Remove(before.Path)
		}
		if err != nil {
			return fmt.Errorf("AGENT_CONFIG_RECOVERY_REQUIRED")
		}
	}
	if os.Remove(path) != nil {
		return fmt.Errorf("MODEL_STORE_WRITE_FAILED")
	}
	return nil
}

func (s *Store) trimBackups() {
	dir := filepath.Join(s.root, "backups")
	entries, _ := os.ReadDir(dir)
	var files []os.FileInfo
	for _, entry := range entries {
		name := entry.Name()
		if len(name) != 37 || !validID.MatchString(name[:32]) || name[32:] != ".json" {
			continue
		}
		if info, err := entry.Info(); err == nil && info.Mode().IsRegular() {
			files = append(files, info)
		}
	}
	sort.Slice(files, func(i, j int) bool { return files[i].ModTime().After(files[j].ModTime()) })
	for i := 20; i < len(files); i++ {
		_ = os.Remove(filepath.Join(dir, files[i].Name()))
	}
}
