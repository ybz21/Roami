package api

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/backend/worktree"
	"github.com/ybz21/Roami/internal/memguard"
	life "github.com/ybz21/Roami/internal/sessionlifecycle"
	"github.com/ybz21/Roami/internal/sessionstore"
)

type lifecycleClosePlan struct {
	Proof     memguard.PaneStopProof `json:"proof"`
	Workspace worktree.Worktree      `json:"workspace"`
	Repo      string                 `json:"repo"`
}
type lifecycleSeal struct {
	FilesHash     string `json:"filesHash"`
	UntrackedHash string `json:"untrackedHash"`
	Branch        string `json:"branch"`
	Snapshot      string `json:"snapshot"`
	Head          string `json:"head"`
}

func (a *API) lifecycleCloseSteps() []life.Step {
	return []life.Step{
		{Name: "inspect", Run: a.lifecycleInspectClose},
		{Name: "stop", Run: a.lifecycleStop},
		{Name: "seal", Run: a.lifecycleSeal},
		{Name: "commit", Run: a.lifecycleCommit},
		{Name: "merge", Run: a.lifecycleMerge},
		{Name: "remove", Run: a.lifecycleRemove},
		{Name: "branch", Run: a.lifecycleDeleteBranch},
		{Name: "trace", Run: a.lifecycleTrace},
	}
}

func (a *API) lifecycleInspectClose(ctx context.Context, o life.Operation) (any, error) {
	rt := lifecycleRuntime(ctx)
	actual, err := rt.SessionIdentity(o.ResourceID)
	if err != nil {
		return nil, err
	}
	if actual == "" || actual != o.Intent.SessionIdentity {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
	}
	proof, err := memguard.CapturePaneStopProof(rt.PanePIDs(o.ResourceID))
	if err != nil {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED: %w", err))
	}
	plan := lifecycleClosePlan{Proof: proof}
	if o.Intent.Mode != "keep" {
		path, err := filepath.EvalSymlinks(o.Intent.Path)
		if err != nil {
			return nil, err
		}
		if filepath.Clean(path) != filepath.Clean(o.Intent.Path) {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
		}
		repo, err := a.WT.ResolveRepo(ctx, path)
		if err != nil {
			return nil, err
		}
		plan.Repo = repo.Root
		plan.Workspace, err = a.WT.LifecycleDetails(ctx, path)
		if err != nil {
			return nil, lifecycleFailure(err)
		}
		if plan.Workspace.External {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_WORKSPACE_PROTECTED"))
		}
	}
	return plan, nil
}

func (a *API) lifecycleStop(ctx context.Context, o life.Operation) (any, error) {
	plan, err := life.Result[lifecycleClosePlan](o, "inspect")
	if err != nil {
		return nil, err
	}
	rt := lifecycleRuntime(ctx)
	actual, err := rt.SessionIdentity(o.ResourceID)
	if err != nil {
		return nil, err
	}
	if actual != "" && actual != o.Intent.SessionIdentity {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
	}
	if err = memguard.StopPaneScopes(ctx, plan.Proof); err != nil {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED: %w", err))
	}
	if actual != "" {
		_, _ = a.TT.RunCtx(ctx, "kill", o.ResourceID, "--yes")
	}
	if actual, err = rt.SessionIdentity(o.ResourceID); err != nil || actual != "" {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED"))
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	if err = meta.OnKill(o.ResourceID); err != nil {
		return nil, err
	}
	return true, nil
}

func (a *API) lifecycleSeal(ctx context.Context, o life.Operation) (any, error) {
	if o.Intent.Mode == "keep" {
		return lifecycleSeal{}, nil
	}
	state, err := a.WT.SnapshotState(ctx, o.Intent.Path)
	if err != nil {
		return nil, err
	}
	if state.Fingerprint != o.Intent.Snapshot {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_WORKSPACE_CHANGED"))
	}
	return sealedSnapshot(state), nil
}

func (a *API) lifecycleCommit(ctx context.Context, o life.Operation) (any, error) {
	if o.Intent.Mode != "merge" {
		return nil, nil
	}
	if o.Has("commit-intent") {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_RESULT_UNKNOWN"))
	}
	seal, err := life.Result[lifecycleSeal](o, "seal")
	if err != nil {
		return nil, err
	}
	actual, err := a.WT.Snapshot(ctx, o.Intent.Path)
	if err != nil {
		return nil, err
	}
	if actual != seal.Snapshot {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_WORKSPACE_CHANGED"))
	}
	_, err = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error { o.Receipts["commit-intent"] = json.RawMessage(`true`); return nil })
	if err != nil {
		return nil, err
	}
	if err = a.WT.CommitAll(ctx, o.Intent.Path, "wip: prepare session cleanup "+o.ID); err != nil {
		return nil, err
	}
	state, err := a.WT.SnapshotState(ctx, o.Intent.Path)
	if err != nil {
		return nil, err
	}
	if state.FilesHash != seal.FilesHash || state.Branch != seal.Branch || !state.Clean {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_WORKSPACE_CHANGED"))
	}
	if state.Head != seal.Head {
		matches, e := a.WT.LifecycleCommitMatches(ctx, o.Intent.Path, seal.Head, "wip: prepare session cleanup "+o.ID)
		if e != nil {
			return nil, e
		}
		if !matches {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_WORKSPACE_CHANGED"))
		}
	}
	return sealedSnapshot(state), nil
}

func (a *API) lifecycleMerge(ctx context.Context, o life.Operation) (any, error) {
	if o.Intent.Mode != "merge" {
		return nil, nil
	}
	if o.Has("merge-intent") {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_RESULT_UNKNOWN"))
	}
	seal, err := life.Result[lifecycleSeal](o, "commit")
	if err != nil {
		return nil, err
	}
	actual, err := a.WT.Snapshot(ctx, o.Intent.Path)
	if err != nil {
		return nil, err
	}
	if actual != seal.Snapshot {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_WORKSPACE_CHANGED"))
	}
	_, err = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error { o.Receipts["merge-intent"] = json.RawMessage(`true`); return nil })
	if err != nil {
		return nil, err
	}
	strategy := o.Intent.Strategy
	if strategy == "" {
		strategy = "squash"
	}
	result, err := a.WT.Merge(ctx, worktree.MergeReq{Path: o.Intent.Path, Strategy: strategy, ExpectedHead: seal.Head})
	if err != nil {
		if strings.HasPrefix(err.Error(), "LIFECYCLE_RESULT_UNKNOWN") || ctx.Err() != nil {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_RESULT_UNKNOWN: %w", err))
		}
		// A returned conflict is known, unlike a process exit between merge and checkpoint.
		latest, e := a.Lifecycle.Get(o.ID)
		if e != nil {
			return nil, e
		}
		_, e = a.Lifecycle.Mutate(o.ID, latest.Revision, func(o *life.Operation) error { delete(o.Receipts, "merge-intent"); return nil })
		if e != nil {
			return nil, e
		}
		return nil, err
	}
	state, err := a.WT.SnapshotState(ctx, o.Intent.Path)
	if err != nil {
		return nil, err
	}
	if !state.Clean || state.UntrackedHash != seal.UntrackedHash || state.Branch != seal.Branch || state.Head != result.SourceOid || (strategy != "rebase" && state.FilesHash != seal.FilesHash) {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_WORKSPACE_CHANGED"))
	}
	return struct {
		lifecycleSeal
		Merge worktree.MergeResp `json:"merge"`
	}{sealedSnapshot(state), result}, nil
}

func cleanupSeal(o life.Operation) (lifecycleSeal, error) {
	if o.Intent.Mode == "merge" {
		return life.Result[lifecycleSeal](o, "merge")
	}
	return life.Result[lifecycleSeal](o, "seal")
}

func (a *API) lifecycleRemove(ctx context.Context, o life.Operation) (any, error) {
	if o.Intent.Mode == "keep" {
		return nil, nil
	}
	seal, err := cleanupSeal(o)
	if err != nil {
		return nil, err
	}
	plan, err := life.Result[lifecycleClosePlan](o, "inspect")
	if err != nil {
		return nil, err
	}
	verify := func() (any, error) {
		complete, e := a.WT.RemovalComplete(ctx, plan.Repo, o.Intent.Path)
		if e != nil {
			return nil, e
		}
		if !complete {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_CLEANUP_INCOMPLETE"))
		}
		return true, nil
	}
	if _, err = os.Lstat(o.Intent.Path); os.IsNotExist(err) {
		// The removal intent pins the old directory. An absent path alone is not ownership proof.
		if !o.Has("remove-intent") {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
		}
		return verify()
	} else if err != nil {
		return nil, err
	}
	if !o.Has("remove-intent") {
		_, err = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error { o.Receipts["remove-intent"] = json.RawMessage(`true`); return nil })
		if err != nil {
			return nil, err
		}
	}
	if err = a.WT.Remove(ctx, worktree.RemoveReq{Path: o.Intent.Path, ExpectedSnapshot: seal.Snapshot, ForceWorktree: o.Intent.Mode == "discard"}); err != nil {
		return nil, lifecycleFailure(err)
	}
	return verify()
}

func (a *API) lifecycleDeleteBranch(ctx context.Context, o life.Operation) (any, error) {
	if o.Intent.Mode == "keep" || o.Intent.KeepBranch {
		return nil, nil
	}
	plan, err := life.Result[lifecycleClosePlan](o, "inspect")
	if err != nil {
		return nil, err
	}
	if plan.Workspace.Adopted || plan.Workspace.Branch == "" {
		return nil, nil
	}
	seal, err := cleanupSeal(o)
	if err != nil {
		return nil, err
	}
	force := o.Intent.Mode == "discard" || o.Intent.Strategy == "squash" || o.Intent.Strategy == ""
	if err = a.WT.DeleteLifecycleBranch(ctx, plan.Repo, plan.Workspace.Branch, seal.Head, force); err != nil {
		return nil, lifecycleFailure(err)
	}
	return true, nil
}

func (a *API) lifecycleTrace(ctx context.Context, o life.Operation) (any, error) {
	if o.Intent.Mode == "keep" {
		return nil, nil
	}
	plan, err := life.Result[lifecycleClosePlan](o, "inspect")
	if err != nil {
		return nil, err
	}
	action := "discarded"
	if o.Intent.Mode == "merge" {
		action = "merged"
	} else if plan.Workspace.MergedInto != "" {
		action = "cleaned"
	}
	a.Projects.Trace(project.TraceEntry{ID: o.ID, Repo: plan.Repo, Branch: plan.Workspace.Branch, HeadOid: plan.Workspace.Head, Base: plan.Workspace.Base, Action: action, Strategy: o.Intent.Strategy, MergedInto: plan.Workspace.MergedInto, MergedKind: plan.Workspace.MergedKind})
	return true, nil
}

func sealedSnapshot(state worktree.LifecycleSnapshot) lifecycleSeal {
	return lifecycleSeal{Snapshot: state.Fingerprint, FilesHash: state.FilesHash, UntrackedHash: state.UntrackedHash, Head: state.Head, Branch: state.Branch}
}
