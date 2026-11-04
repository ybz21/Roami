package okr

import (
	"errors"
	"io/fs"
)

// ConfigReadOnly resolves confirmed configuration without migrations, exports, or cache writes.
func (s *Store) ConfigReadOnly(projectID string) (*Config, error) {
	if s.projects == nil {
		w, err := read(s.db, projectID)
		if err != nil || w == nil {
			return nil, err
		}
		return &w.Config, nil
	}
	marked, err := s.marked(projectID)
	if err != nil {
		return nil, err
	}
	root, err := s.openBundle(projectID, false)
	if err == nil {
		defer root.Close()
		snapshot, snapshotErr := loadSnapshot(root)
		if snapshotErr == nil {
			return &snapshot.Workspace.Config, nil
		}
		_, pointerErr := root.Lstat("state/current.json")
		if marked || pointerErr == nil || !errors.Is(snapshotErr, fs.ErrNotExist) {
			return nil, snapshotErr
		}
	} else if marked || !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	w, err := read(s.db, projectID)
	if err != nil || w == nil {
		return nil, err
	}
	return &w.Config, nil
}
