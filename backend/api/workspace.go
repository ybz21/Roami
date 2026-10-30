package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"sync"

	"github.com/gin-gonic/gin"
)

type WorkspaceFile struct {
	Path    string `json:"path"`
	Preview bool   `json:"preview"`
	Mode    string `json:"mode"`
	Task    string `json:"task"`
}

type WorkspaceState struct {
	Revision   uint64          `json:"revision"`
	Terms      []string        `json:"terms"`
	Active     string          `json:"active"`
	Files      []WorkspaceFile `json:"files"`
	ActiveFile string          `json:"activeFile"`
}

// Changes apply to the latest state, so a stale client cannot replace another client's tabs.
type WorkspaceChange struct {
	Add         []string        `json:"add"`
	Remove      []string        `json:"remove"`
	Order       []string        `json:"order"`
	Active      *string         `json:"active"`
	Files       []WorkspaceFile `json:"files"`
	RemoveFiles []string        `json:"removeFiles"`
	ActiveFile  *string         `json:"activeFile"`
}

type WorkspaceStore struct {
	mu   sync.Mutex
	file string
}

func NewWorkspaceStore(dataDir string) *WorkspaceStore {
	return &WorkspaceStore{file: filepath.Join(dataDir, "workspace.json")}
}

func (s *WorkspaceStore) read() (WorkspaceState, error) {
	state := WorkspaceState{Terms: []string{}, Files: []WorkspaceFile{}}
	b, err := os.ReadFile(s.file)
	if errors.Is(err, os.ErrNotExist) {
		return state, nil
	}
	if err != nil {
		return state, err
	}
	err = json.Unmarshal(b, &state)
	return state, err
}

func applyWorkspaceChange(state *WorkspaceState, change WorkspaceChange) {
	state.Terms = slices.DeleteFunc(state.Terms, func(id string) bool { return slices.Contains(change.Remove, id) })
	for _, id := range change.Add {
		if id != "" && !slices.Contains(state.Terms, id) {
			state.Terms = append(state.Terms, id)
		}
	}
	if change.Order != nil {
		ordered := []string{}
		for _, id := range append(change.Order, state.Terms...) {
			if slices.Contains(state.Terms, id) && !slices.Contains(ordered, id) {
				ordered = append(ordered, id)
			}
		}
		state.Terms = ordered
	}
	if change.Active != nil {
		state.Active = *change.Active
	}
	if !slices.Contains(state.Terms, state.Active) {
		state.Active = ""
		if len(state.Terms) > 0 {
			state.Active = state.Terms[len(state.Terms)-1]
		}
	}
	state.Files = slices.DeleteFunc(state.Files, func(file WorkspaceFile) bool { return slices.Contains(change.RemoveFiles, file.Path) })
	for _, file := range change.Files {
		if file.Path == "" {
			continue
		}
		i := slices.IndexFunc(state.Files, func(f WorkspaceFile) bool { return f.Path == file.Path })
		if i < 0 {
			state.Files = append(state.Files, file)
		} else {
			state.Files[i] = file
		}
	}
	if change.ActiveFile != nil {
		state.ActiveFile = *change.ActiveFile
	}
	if !slices.ContainsFunc(state.Files, func(f WorkspaceFile) bool { return f.Path == state.ActiveFile }) {
		state.ActiveFile = ""
	}
}

func (s *WorkspaceStore) update(seed *WorkspaceState, changes []WorkspaceChange) (WorkspaceState, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	state, err := s.read()
	if err != nil {
		return state, err
	}
	if state.Revision == 0 && seed != nil {
		applyWorkspaceChange(&state, WorkspaceChange{Add: seed.Terms, Active: &seed.Active, Files: seed.Files, ActiveFile: &seed.ActiveFile})
	}
	for _, change := range changes {
		applyWorkspaceChange(&state, change)
	}
	state.Revision++
	b, err := json.Marshal(state)
	if err != nil {
		return state, err
	}
	if err = os.MkdirAll(filepath.Dir(s.file), 0o700); err != nil {
		return state, err
	}
	if err = os.WriteFile(s.file+".tmp", b, 0o600); err != nil {
		return state, err
	}
	err = os.Rename(s.file+".tmp", s.file)
	return state, err
}

func (a *API) GetWorkspace(c *gin.Context) {
	a.Workspace.mu.Lock()
	state, err := a.Workspace.read()
	a.Workspace.mu.Unlock()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "READ_ERROR"}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": state})
}

func (a *API) ChangeWorkspace(c *gin.Context) {
	var request struct {
		Seed    *WorkspaceState   `json:"seed"`
		Changes []WorkspaceChange `json:"changes"`
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 1<<20)
	if c.ShouldBindJSON(&request) != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	state, err := a.Workspace.update(request.Seed, request.Changes)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "WRITE_ERROR"}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": state})
}
