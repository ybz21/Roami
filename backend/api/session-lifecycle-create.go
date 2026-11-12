package api

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/backend/worktree"
	"github.com/ybz21/Roami/internal/memguard"
	life "github.com/ybz21/Roami/internal/sessionlifecycle"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

type lifecycleWorkspace struct {
	worktree.CreateResp
	Snapshot string `json:"snapshot"`
	Owned    bool   `json:"owned"`
}
type lifecycleSession struct {
	Identity string `json:"identity"`
}

func (a *API) lifecycleSteps(o life.Operation) []life.Step {
	if o.Kind == "close" {
		return a.lifecycleCloseSteps()
	}
	return []life.Step{
		{Name: "workspace", Run: a.lifecyclePrepareWorkspace},
		{Name: "session", Run: a.lifecyclePrepareSession},
		{Name: "track", Run: a.lifecycleTrack},
		{Name: "launch", Run: a.lifecycleLaunch},
		{Name: "compensate", Run: a.lifecycleCompensate},
	}
}

func (a *API) lifecyclePrepareWorkspace(ctx context.Context, o life.Operation) (any, error) {
	if o.CancelRequested {
		if o.Has("workspace-intent") {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_RESULT_UNKNOWN"))
		}
		return lifecycleWorkspace{}, nil
	}
	rt := lifecycleRuntime(ctx)
	if err := rt.CheckLifecycle(o.Intent.Parent, o.Intent.Dir); err != nil {
		return nil, lifecycleFailure(err)
	}
	if o.Intent.Parent != "" {
		identity, err := rt.SessionIdentity(o.Intent.Parent)
		if err != nil || identity == "" || (o.Intent.ParentIdentity != "" && identity != o.Intent.ParentIdentity) {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_PARENT_UNAVAILABLE"))
		}
	}
	info, err := os.Stat(o.Intent.Dir)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("not a directory")
	}
	prepared := lifecycleWorkspace{CreateResp: worktree.CreateResp{Path: o.Intent.Dir, Branch: o.Intent.Branch, Base: o.Intent.Base}}
	if o.Intent.Worktree {
		planned := struct {
			Path string `json:"path"`
		}{}
		if o.Has("workspace-intent") {
			if err = o.Receipt("workspace-intent", &planned); err != nil {
				return nil, err
			}
		} else {
			repo, e := a.WT.ResolveRepo(ctx, o.Intent.Dir)
			if e != nil {
				return nil, e
			}
			planned.Path = filepath.Join(repo.Root, ".worktrees", o.ResourceID)
			encoded, _ := json.Marshal(planned)
			o, e = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error { o.Receipts["workspace-intent"] = encoded; return nil })
			if e != nil {
				return nil, e
			}
		}
		branch := o.Intent.Branch
		if branch == "" {
			branch = autoBranch(o.Intent.Name)
		}
		prepared.CreateResp, err = a.WT.Create(ctx, worktree.CreateReq{Dir: o.Intent.Dir, Branch: branch, Base: o.Intent.Base, Remote: o.Intent.Remote, Dirname: o.ResourceID, Existing: o.Intent.Existing, OperationID: o.ID, ExpectedPath: planned.Path})
		if err != nil {
			return nil, lifecycleFailure(err)
		}
		prepared.Owned = true
		prepared.Snapshot, err = a.WT.Snapshot(ctx, prepared.Path)
		if err != nil {
			return nil, err
		}
	}
	return prepared, nil
}

func (a *API) lifecyclePrepareSession(ctx context.Context, o life.Operation) (any, error) {
	if o.CancelRequested {
		if o.Has("session-intent") {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_RESULT_UNKNOWN"))
		}
		return lifecycleSession{}, nil
	}
	prepared, err := life.Result[lifecycleWorkspace](o, "workspace")
	if err != nil {
		return nil, err
	}
	rt := lifecycleRuntime(ctx)
	if o.Intent.Parent != "" {
		release, e := rt.InputLease("=" + o.Intent.Parent)
		if e != nil {
			return nil, lifecycleFailure(e)
		}
		defer release()
		identity, e := rt.SessionIdentity(o.Intent.Parent)
		if e != nil || identity == "" || (o.Intent.ParentIdentity != "" && identity != o.Intent.ParentIdentity) {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_PARENT_UNAVAILABLE"))
		}
	}
	identity, err := rt.SessionIdentity(o.ResourceID)
	if err != nil {
		return nil, err
	}
	if identity != "" {
		owner, e := rt.TmuxOutput("show-environment", "-t", "="+o.ResourceID, "ROAMI_LIFECYCLE_OPERATION")
		if e != nil || strings.TrimSpace(owner) != "ROAMI_LIFECYCLE_OPERATION="+o.ID {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
		}
	} else {
		if !o.Has("session-intent") {
			o, err = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error { o.Receipts["session-intent"] = json.RawMessage(`true`); return nil })
			if err != nil {
				return nil, err
			}
		}
		rt.SetGlobalEnv()
		_, err = rt.CreateSession(runtime.CreateOpts{ReservedName: o.ResourceID, OperationID: o.ID, Label: o.Intent.Name, Dir: prepared.Path})
		if err != nil {
			return nil, lifecycleFailure(err)
		}
		identity, err = rt.SessionIdentity(o.ResourceID)
		if err != nil || identity == "" {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_RESULT_UNKNOWN"))
		}
	}
	rt.InjectEnv(o.ResourceID)
	cwd, err := rt.TmuxOutput("list-panes", "-t", "="+o.ResourceID, "-F", "#{pane_current_path}")
	if err != nil || filepath.Clean(strings.Split(strings.TrimSpace(cwd), "\n")[0]) != filepath.Clean(prepared.Path) {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_WORKSPACE_NOT_READY"))
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	if err = meta.Put(sessmeta.Row{Session: o.ResourceID, Parent: o.Intent.Parent, CreatedBy: "lifecycle", InitialCwd: prepared.Path}); err != nil {
		return nil, err
	}
	repo, _ := a.WT.ResolveRepo(ctx, prepared.Path)
	if err = meta.SetHome(o.ResourceID, prepared.Path, repo.Root); err != nil {
		return nil, err
	}
	a.WT.BindSessionHome(o.ResourceID, prepared.Path)
	return lifecycleSession{Identity: identity}, nil
}

func (a *API) lifecycleTrack(ctx context.Context, o life.Operation) (any, error) {
	if o.CancelRequested || o.Intent.Launch == nil || !o.Intent.Launch.AutoReview {
		return nil, nil
	}
	prepared, err := life.Result[lifecycleWorkspace](o, "workspace")
	if err != nil {
		return nil, err
	}
	out, err := a.TT.RunCtx(ctx, "plugin", "track", o.ResourceID, "--label", "review:auto=true", "--label", "role=author", "--label", "workdir="+prepared.Path)
	if err != nil {
		return nil, fmt.Errorf("track: %s: %w", out, err)
	}
	return true, nil
}

// The dispatch marker is committed before submission. Unknown delivery is never blindly replayed.
func (a *API) lifecycleLaunch(ctx context.Context, o life.Operation) (any, error) {
	if o.CancelRequested || o.Intent.Launch == nil || o.Intent.Launch.Command == "" {
		return nil, nil
	}
	if o.Has("launch-intent") {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_RESULT_UNKNOWN"))
	}
	prepared, err := life.Result[lifecycleWorkspace](o, "workspace")
	if err != nil {
		return nil, err
	}
	session, err := life.Result[lifecycleSession](o, "session")
	if err != nil {
		return nil, err
	}
	rt := lifecycleRuntime(ctx)
	actual, err := rt.SessionIdentity(o.ResourceID)
	if err != nil || actual != session.Identity {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
	}
	launch := o.Intent.Launch
	command := launch.Command
	if strings.TrimSpace(launch.Task) != "" {
		guide, err := readAgentCapabilities()
		if err != nil {
			return nil, err
		}
		executionGuide, err := readSessionExecutionGuide()
		if err != nil {
			return nil, err
		}
		guide = executionGuide + "\n\n" + strings.TrimSpace(guide)
		fileBase := launch.FileBase
		if !(fileBase == "/api/file" || (strings.HasPrefix(fileBase, "/n/") && strings.HasSuffix(fileBase, "/api/file") && !strings.ContainsAny(fileBase, "\r\n?#"))) {
			fileBase = "/api/file"
		}
		guide = strings.NewReplacer("{{FILE_BASE}}", fileBase, "{{FILE_RAW_BASE}}", fileBase+"/raw", "{{FILE_SERVE_BASE}}", fileBase+"/serve").Replace(guide)
		preamble := strings.NewReplacer("{{PATH}}", prepared.Path, "{{BASE}}", prepared.Base, "{{BRANCH}}", prepared.Branch, "{{SESSION}}", o.ResourceID).Replace(launch.Preamble)
		prompt := launch.TaskHeading + "\n\n" + strings.TrimSpace(launch.Task) + "\n\n" + launch.SetupHeading + "\n\n" + preamble + "\n\n" + strings.TrimSpace(guide)
		if launch.Agent == "opencode" {
			command += " --prompt"
		}
		command += " " + shellQuote(prompt)
	}
	_, err = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error { o.Receipts["launch-intent"] = json.RawMessage(`true`); return nil })
	if err != nil {
		return nil, err
	}
	if err = rt.SendShellCommand("="+o.ResourceID+":", command); err != nil {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_RESULT_UNKNOWN: %w", err))
	}
	return true, nil
}

func (a *API) lifecycleCompensate(ctx context.Context, o life.Operation) (any, error) {
	if !o.CancelRequested {
		return nil, nil
	}
	rt := lifecycleRuntime(ctx)
	identity, err := rt.SessionIdentity(o.ResourceID)
	if err != nil {
		return nil, err
	}
	var proof memguard.PaneStopProof
	if o.Has("cancel-stop-intent") {
		if err = o.Receipt("cancel-stop-intent", &proof); err != nil {
			return nil, err
		}
	}
	if identity == "" && len(proof.Scopes) == 0 {
		if session, e := life.Result[lifecycleSession](o, "session"); e == nil && session.Identity != "" {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED"))
		}
	}
	if identity != "" {
		session, e := life.Result[lifecycleSession](o, "session")
		if e != nil || identity != session.Identity {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
		}
		if len(proof.Scopes) == 0 {
			proof, e = memguard.CapturePaneStopProof(rt.PanePIDs(o.ResourceID))
			if e != nil {
				return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED: %w", e))
			}
			encoded, _ := json.Marshal(proof)
			o, e = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error { o.Receipts["cancel-stop-intent"] = encoded; return nil })
			if e != nil {
				return nil, e
			}
		}
	}
	if len(proof.Scopes) > 0 {
		if err = memguard.StopPaneScopes(ctx, proof); err != nil {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED: %w", err))
		}
	}
	if current, e := rt.SessionIdentity(o.ResourceID); e == nil && current != "" {
		session, readErr := life.Result[lifecycleSession](o, "session")
		if readErr != nil || current != session.Identity {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
		}
		if err = rt.Tmux("kill-session", "-t", "="+o.ResourceID); err != nil {
			return nil, err
		}
	}
	if current, e := rt.SessionIdentity(o.ResourceID); e != nil || current != "" {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED"))
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	if err = meta.OnKill(o.ResourceID); err != nil {
		return nil, err
	}
	prepared, err := life.Result[lifecycleWorkspace](o, "workspace")
	if err != nil {
		return nil, err
	}
	if prepared.Owned {
		if _, e := os.Lstat(prepared.Path); os.IsNotExist(e) {
			return true, nil
		}
		owner, e := a.WT.LifecycleOwner(ctx, prepared.Path)
		if e != nil || owner != o.ID {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
		}
		actual, e := a.WT.Snapshot(ctx, prepared.Path)
		if e != nil {
			return nil, e
		}
		if actual != prepared.Snapshot {
			return map[string]any{"retained": true, "path": prepared.Path}, nil
		}
		if e = a.WT.Remove(ctx, worktree.RemoveReq{Path: prepared.Path, ExpectedSnapshot: prepared.Snapshot, DeleteBranch: !o.Intent.Existing, ForceDeleteBranch: !o.Intent.Existing}); e != nil {
			return nil, lifecycleFailure(e)
		}
	}
	return true, nil
}
