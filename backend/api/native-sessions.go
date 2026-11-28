package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionstore"
)

func nativeSessionIdentity(hostID, sessionID string) string {
	return "native:" + hostID + ":" + sessionID
}

func isNativeIdentity(identity string) bool {
	return strings.HasPrefix(identity, "native:")
}

func (a *API) resolveSessionIdentity(ctx context.Context, name string) (string, error) {
	if st, ok := a.nativeSession(ctx, name); ok {
		return nativeSessionIdentity(st.HostInstanceID, st.SessionID), nil
	}
	return lifecycleRuntime(ctx).SessionIdentity(name)
}

func (a *API) submitNativeText(ctx context.Context, name, payload string, enter bool) error {
	if a.NativeBackend == nil {
		return fmt.Errorf("native terminal backend unavailable")
	}
	subCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	_, err := a.NativeBackend.Submit(subCtx, sessionbackend.Target{SessionID: name}, sessionbackend.SubmitReq{
		RequestID:      "api-" + uuid.NewString(),
		Payload:        payload,
		SubmitEnter:    enter,
		BracketedPaste: false,
	})
	return err
}

func (a *API) forkNativeSession(ctx context.Context, parent, label, dir string) (string, error) {
	if a.NativeBackend == nil {
		return "", fmt.Errorf("native terminal backend unavailable")
	}
	dir = strings.TrimSpace(dir)
	if dir == "" {
		if st, ok := a.nativeSession(ctx, parent); ok && strings.TrimSpace(st.Cwd) != "" {
			dir = strings.TrimSpace(st.Cwd)
		} else if home := a.WT.SessionHome(parent); home != "" {
			dir = home
		}
	}
	createCtx, cancel := context.WithTimeout(ctx, 6*time.Second)
	defer cancel()
	ref, err := a.NativeBackend.Create(createCtx, sessionbackend.CreateSpec{
		Label:      strings.TrimSpace(label),
		Dir:        dir,
		LoginShell: true,
	})
	if err != nil {
		return "", err
	}
	rt := lifecycleRuntime(ctx)
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	_ = meta.Put(sessmeta.Row{
		Session:        ref.SessionID,
		Label:          strings.TrimSpace(label),
		Parent:         parent,
		CreatedBy:      "fork",
		InitialCwd:     dir,
		Backend:        string(sessionbackend.BackendNative),
		HostInstanceID: ref.HostInstanceID,
	})
	if dir != "" {
		if repo, err := a.WT.ResolveRepo(ctx, dir); err == nil {
			_ = meta.SetHome(ref.SessionID, dir, repo.Root)
		}
		a.WT.BindSessionHome(ref.SessionID, dir)
	}
	return ref.SessionID, nil
}

func (a *API) nativeSession(ctx context.Context, name string) (sessionbackend.SessionState, bool) {
	if a.NativeBackend == nil || name == "" {
		return sessionbackend.SessionState{}, false
	}
	obsCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	st, err := a.NativeBackend.Observe(obsCtx, name)
	if err != nil || st.Backend != sessionbackend.BackendNative {
		return sessionbackend.SessionState{}, false
	}
	return st, true
}

func (a *API) listNativeSummaries(ctx context.Context) []sessionbackend.SessionSummary {
	if a.NativeBackend == nil {
		return nil
	}
	listCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	rows, err := a.NativeBackend.List(listCtx)
	if err != nil {
		return nil
	}
	out := make([]sessionbackend.SessionSummary, 0, len(rows))
	for _, r := range rows {
		if r.Backend == sessionbackend.BackendNative {
			out = append(out, r)
		}
	}
	return out
}

// mergeNativeSessionsJSON merges native roami-sessiond sessions into /api/sessions JSON output
// (supporting both flat array and tree=1 format) without disturbing tmux rows.
func (a *API) mergeNativeSessionsJSON(ctx context.Context, raw []byte) []byte {
	nativeRows := a.listNativeSummaries(ctx)
	if len(nativeRows) == 0 {
		return raw
	}
	var items []map[string]any
	if err := json.Unmarshal(raw, &items); err != nil {
		return raw
	}
	seen := make(map[string]bool, len(items))
	for _, it := range items {
		if n, ok := it["name"].(string); ok {
			seen[n] = true
		}
	}
	for _, s := range nativeRows {
		if seen[s.ID] {
			continue
		}
		label := s.Label
		if label == "" {
			label = s.ID
		}
		state := "live"
		if s.Status == sessionbackend.StatusExited {
			state = "exited"
		}
		items = append(items, map[string]any{
			"name":           s.ID,
			"id":             s.ID,
			"label":          label,
			"backend":        string(s.Backend),
			"hostInstanceId": s.HostInstanceID,
			"windows":        s.Windows,
			"created":        strconv.FormatInt(s.CreatedAt.Unix(), 10),
			"last_activity":  strconv.FormatInt(s.LastActivityAt.Unix(), 10),
			"attached":       s.Attached,
			"state":          state,
			"dir":            s.Dir,
		})
	}
	out, err := json.Marshal(items)
	if err != nil {
		return raw
	}
	return out
}

func (a *API) createNativeSession(ctx context.Context, label, dir string) (string, error) {
	if a.NativeBackend == nil {
		return "", fmt.Errorf("native terminal backend unavailable")
	}
	createCtx, cancel := context.WithTimeout(ctx, 6*time.Second)
	defer cancel()
	ref, err := a.NativeBackend.Create(createCtx, sessionbackend.CreateSpec{
		Label:      strings.TrimSpace(label),
		Dir:        strings.TrimSpace(dir),
		LoginShell: true,
	})
	if err != nil {
		return "", err
	}
	return ref.SessionID, nil
}

func nativeKeyBytes(key string) ([]byte, bool) {
	switch key {
	case "Enter", "C-m":
		return []byte("\r"), true
	case "Escape":
		return []byte("\x1b"), true
	case "Tab":
		return []byte("\t"), true
	case "BSpace":
		return []byte{0x7f}, true
	case "Space":
		return []byte(" "), true
	case "Up":
		return []byte("\x1b[A"), true
	case "Down":
		return []byte("\x1b[B"), true
	case "Right":
		return []byte("\x1b[C"), true
	case "Left":
		return []byte("\x1b[D"), true
	case "C-c":
		return []byte{0x03}, true
	case "C-d":
		return []byte{0x04}, true
	case "C-u":
		return []byte{0x15}, true
	default:
		if len(key) == 1 {
			return []byte(key), true
		}
		return nil, false
	}
}

func (a *API) writeNativeKeys(c *gin.Context, name string, keys []string) {
	var buf []byte
	for _, k := range keys {
		b, ok := nativeKeyBytes(k)
		if !ok {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_KEY", "message": k}})
			return
		}
		buf = append(buf, b...)
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	target := sessionbackend.Target{SessionID: name}
	lease, err := a.NativeBackend.ClaimControl(ctx, target, "api-keys-"+uuid.NewString())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "NATIVE_ERROR", "message": err.Error()}})
		return
	}
	defer func() {
		_ = a.NativeBackend.ReleaseControl(context.Background(), target, lease.Controller, lease.ControlGen)
	}()
	if err := a.NativeBackend.WriteInput(ctx, target, lease.ControlGen, buf); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "NATIVE_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": "ok"})
}
