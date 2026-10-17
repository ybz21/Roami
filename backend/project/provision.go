package project

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unicode/utf8"

	"github.com/ybz21/Roami/backend/worktree"
)

type ProvisionReceipt struct {
	Key     string `json:"key"`
	Dir     string `json:"dir"`
	Name    string `json:"name"`
	Git     bool   `json:"git"`
	Created bool   `json:"created"`
}

type projectProvision struct {
	Directory string            `json:"directory"`
	Name      string            `json:"name"`
	Receipt   *ProvisionReceipt `json:"receipt,omitempty"`
}

func writeProvision(path string, value any) error {
	content, err := json.Marshal(value)
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(filepath.Dir(path), ".provision-")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	if err = file.Chmod(0600); err == nil {
		_, err = file.Write(content)
	}
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	if err = os.Rename(file.Name(), path); err != nil {
		return err
	}
	parent, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer parent.Close()
	return parent.Sync()
}

// Provision never adopts an unowned directory or recreates a removed ready project.
func (s *Store) Provision(ctx context.Context, key, name, baseDir, directory string) (ProvisionReceipt, error) {
	if err := ctx.Err(); err != nil {
		return ProvisionReceipt{}, err
	}
	name = strings.TrimSpace(name)
	if key == "" || len(key) > 500 || name == "" || name == "." || name == ".." || strings.ContainsAny(name, "/\\\x00") || utf8.RuneCountInString(name) > 160 || s.dataDir == "" {
		return ProvisionReceipt{}, fmt.Errorf("INVALID_PROJECT_PROVISION")
	}
	if directory != "" && baseDir != "" {
		return ProvisionReceipt{}, fmt.Errorf("INVALID_PROJECT_PROVISION")
	}
	if directory == "" {
		if baseDir == "" {
			baseDir = filepath.Join(s.dataDir, "projects")
		}
		directory = filepath.Join(baseDir, name)
	}
	if !filepath.IsAbs(directory) {
		return ProvisionReceipt{}, fmt.Errorf("BAD_DIR")
	}
	ancestor := filepath.Dir(directory)
	for {
		if _, e := os.Stat(ancestor); e == nil {
			break
		} else if !os.IsNotExist(e) {
			return ProvisionReceipt{}, e
		}
		next := filepath.Dir(ancestor)
		if next == ancestor {
			break
		}
		ancestor = next
	}
	if _, e := worktree.WorktreeRoot(ctx, ancestor); e == nil {
		return ProvisionReceipt{}, fmt.Errorf("PROJECT_PARENT_IS_GIT_WORKTREE")
	}
	if err := os.MkdirAll(filepath.Dir(directory), 0755); err != nil {
		return ProvisionReceipt{}, err
	}
	parent, err := filepath.EvalSymlinks(filepath.Dir(directory))
	if err != nil {
		return ProvisionReceipt{}, err
	}
	directory = filepath.Join(parent, filepath.Base(filepath.Clean(directory)))
	if _, err = worktree.WorktreeRoot(ctx, parent); err == nil {
		return ProvisionReceipt{}, fmt.Errorf("PROJECT_PARENT_IS_GIT_WORKTREE")
	}
	if err = ctx.Err(); err != nil {
		return ProvisionReceipt{}, err
	}
	journal := filepath.Join(s.dataDir, "project-provisions")
	if err = os.MkdirAll(journal, 0700); err != nil {
		return ProvisionReceipt{}, err
	}
	guard, err := os.OpenFile(filepath.Join(journal, "provision.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return ProvisionReceipt{}, err
	}
	defer guard.Close()
	if err = syscall.Flock(int(guard.Fd()), syscall.LOCK_EX); err != nil {
		return ProvisionReceipt{}, err
	}
	defer syscall.Flock(int(guard.Fd()), syscall.LOCK_UN)
	if err = ctx.Err(); err != nil {
		return ProvisionReceipt{}, err
	}
	digest := sha256.Sum256([]byte(key))
	token := hex.EncodeToString(digest[:])
	path := filepath.Join(journal, token+".json")
	intent := projectProvision{Directory: directory, Name: name}
	existed := false
	if content, e := os.ReadFile(path); e == nil {
		existed = true
		var prior projectProvision
		if json.Unmarshal(content, &prior) != nil {
			return ProvisionReceipt{}, fmt.Errorf("PROJECT_PROVISION_CORRUPT")
		}
		if prior.Directory != directory || prior.Name != name {
			return ProvisionReceipt{}, fmt.Errorf("PROJECT_PROVISION_KEY_CONFLICT")
		}
		if prior.Receipt != nil {
			entry, ok := s.Entry(prior.Receipt.Key)
			info, e := os.Lstat(directory)
			if !ok || entry.Dir != directory || e != nil || !info.IsDir() {
				return ProvisionReceipt{}, fmt.Errorf("PROJECT_PROVISION_TARGET_REMOVED")
			}
			return *prior.Receipt, nil
		}
	} else if !os.IsNotExist(e) {
		return ProvisionReceipt{}, e
	}
	for id, entry := range s.Entries() {
		display := entry.DisplayName
		if display == "" {
			display = filepath.Base(entry.Dir)
		}
		if strings.EqualFold(display, name) && entry.Dir != directory {
			return ProvisionReceipt{}, fmt.Errorf("PROJECT_NAME_CONFLICT: %s", id)
		}
	}
	marker := filepath.Join(directory, ".roami-project-provision")
	if !existed {
		if _, e := os.Lstat(directory); !os.IsNotExist(e) {
			return ProvisionReceipt{}, fmt.Errorf("PROJECT_DIRECTORY_EXISTS")
		}
		if err = writeProvision(path, intent); err != nil {
			return ProvisionReceipt{}, err
		}
	}
	if err = os.Mkdir(directory, 0755); err != nil {
		content, e := os.ReadFile(marker)
		if !os.IsExist(err) || e != nil || string(content) != `"`+token+`"` {
			return ProvisionReceipt{}, fmt.Errorf("PROJECT_PROVISION_OUTCOME_UNKNOWN")
		}
	} else {
		if err = writeProvision(marker, token); err != nil {
			return ProvisionReceipt{}, err
		}
	}
	// The marker is encoded JSON so a crash can verify ownership before registration.
	content, err := os.ReadFile(marker)
	if err != nil {
		return ProvisionReceipt{}, err
	}
	var ownedToken string
	if json.Unmarshal(content, &ownedToken) != nil || ownedToken != token {
		return ProvisionReceipt{}, fmt.Errorf("PROJECT_PROVISION_OUTCOME_UNKNOWN")
	}
	parentFile, e := os.Open(parent)
	if e != nil {
		return ProvisionReceipt{}, e
	}
	e = parentFile.Sync()
	parentFile.Close()
	if e != nil {
		return ProvisionReceipt{}, e
	}
	id, _ := s.Add(directory, name)
	if s.db.OK() {
		var saved string
		if err = s.db.QueryRow("SELECT dir FROM projects WHERE id=?", id).Scan(&saved); err != nil || saved != directory {
			return ProvisionReceipt{}, fmt.Errorf("PROJECT_PROVISION_CATALOG_UNAVAILABLE")
		}
	} else {
		content, e := os.ReadFile(s.path)
		var saved fileShape
		if e != nil || json.Unmarshal(content, &saved) != nil || saved.Repos[id] == nil || saved.Repos[id].Dir != directory {
			return ProvisionReceipt{}, fmt.Errorf("PROJECT_PROVISION_CATALOG_UNAVAILABLE")
		}
	}
	receipt := ProvisionReceipt{Key: id, Dir: directory, Name: name, Created: true}
	intent.Receipt = &receipt
	if err = writeProvision(path, intent); err != nil {
		return ProvisionReceipt{}, err
	}
	_ = os.Remove(marker)
	return receipt, nil
}
