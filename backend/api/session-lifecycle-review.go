package api

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/id"
	"github.com/ybz21/Roami/internal/memguard"
	life "github.com/ybz21/Roami/internal/sessionlifecycle"
	"github.com/ybz21/Roami/internal/sessionreview"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

type reviewPlan struct {
	Session string `json:"session"`
	Base    string `json:"base"`
}

func (a *API) lifecycleReview(ctx context.Context, o life.Operation) (any, error) {
	if o.CancelRequested {
		return nil, nil
	}
	spec := o.Intent.Review
	if spec == nil {
		return nil, a.stopLifecycleReview(ctx, o)
	}
	prepared, err := life.Result[lifecycleWorkspace](o, "workspace")
	if err != nil {
		return nil, err
	}
	rt := lifecycleRuntime(ctx)
	runner := agent.Get(spec.Agent)
	if runner == nil || !agent.Describe(runner).Interactive {
		return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_REVIEW_INVALID"))
	}
	fields := strings.Fields(spec.Command)
	if len(fields) > 0 && fields[0] == runner.Bin() {
		if _, err = agent.ResolveBinary(spec.Agent); err != nil {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_REVIEW_NOT_READY: %w", err))
		}
	}
	plan := reviewPlan{}
	if o.Has("review-intent") {
		if err = o.Receipt("review-intent", &plan); err != nil {
			return nil, err
		}
	} else {
		plan.Base, err = sessionreview.Baseline(ctx, prepared.Path)
		if err != nil {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_REVIEW_REPOSITORY: %w", err))
		}
		plan.Session = id.NewAt(time.Now())
		o, err = a.reviewCheckpoint(o, "review-intent", plan)
		if err != nil {
			return nil, err
		}
	}
	authorSession, err := life.Result[lifecycleSession](o, "session")
	if err != nil {
		return nil, err
	}
	author, err := reviewEndpoint(rt, o.ResourceID, authorSession.Identity, o.Intent.Launch.Agent)
	if err != nil {
		return nil, lifecycleFailure(err)
	}
	reviewer, next, err := a.prepareReviewChild(rt, o, plan, prepared.Path, spec.Agent)
	if err != nil {
		return nil, err
	}
	o = next
	if !o.Has("review-launch-intent") {
		prompt := reviewerPromptForPair(author.Session, o.Intent.Launch.Task)
		command := spec.Command
		if flag := agent.Describe(runner).PromptFlag; flag != "" {
			command += " " + flag
		}
		command += " " + shellQuote(prompt)
		o, err = a.reviewCheckpoint(o, "review-launch-intent", true)
		if err != nil {
			return nil, err
		}
		if err = rt.SendShellCommand("="+reviewer.Session+":", command); err != nil {
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_REVIEW_NOT_READY: %w", err))
		}
	}
	wait, stop := context.WithTimeout(ctx, 75*time.Second)
	defer stop()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for !reviewLaunchReady(rt, reviewer) {
		current, err := a.Lifecycle.Get(o.ID)
		if err != nil || current.CancelRequested {
			return nil, err
		}
		select {
		case <-wait.Done():
			return nil, lifecycleFailure(fmt.Errorf("LIFECYCLE_REVIEW_NOT_READY"))
		case <-ticker.C:
		}
	}
	pair := sessionreview.Pair{Author: author, Reviewer: reviewer, Directory: prepared.Path, Base: plan.Base, Trigger: spec.Trigger}
	if err = sessionreview.Open(rt).Bind(ctx, pair); err != nil {
		return nil, err
	}
	return reviewer, nil
}

func (a *API) reviewCheckpoint(o life.Operation, key string, value any) (life.Operation, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return o, err
	}
	return a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error {
		o.Receipts[key] = encoded
		return nil
	})
}

func (a *API) prepareReviewChild(rt runtime.Runtime, o life.Operation, plan reviewPlan, directory, kind string) (sessionreview.Endpoint, life.Operation, error) {
	var endpoint sessionreview.Endpoint
	identity, err := rt.SessionIdentity(plan.Session)
	if err != nil {
		return endpoint, o, err
	}
	if o.Has("review-endpoint-intent") {
		err = o.Receipt("review-endpoint-intent", &endpoint)
		if err != nil || endpoint.Session != plan.Session || endpoint.Identity != identity || identity == "" {
			return endpoint, o, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
		}
		return endpoint, o, nil
	}
	if identity == "" {
		if _, err = rt.CreateSession(runtime.CreateOpts{ReservedName: plan.Session, OperationID: o.ID, Label: "review", Dir: directory}); err != nil {
			return endpoint, o, err
		}
		identity, err = rt.SessionIdentity(plan.Session)
		if err != nil || identity == "" {
			return endpoint, o, lifecycleFailure(fmt.Errorf("LIFECYCLE_REVIEW_NOT_READY"))
		}
	}
	if err = verifyReviewOwner(rt, plan.Session, o.ID); err != nil {
		return endpoint, o, err
	}
	if err = rt.InjectEnv(plan.Session); err != nil {
		return endpoint, o, err
	}
	endpoint, err = reviewEndpoint(rt, plan.Session, identity, kind)
	if err != nil {
		return endpoint, o, err
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	if err = meta.Put(sessmeta.Row{Session: plan.Session, Parent: o.ResourceID, CreatedBy: "review", InitialCwd: directory}); err != nil {
		return endpoint, o, err
	}
	if err = meta.SetAgentKind(plan.Session, kind); err != nil {
		return endpoint, o, err
	}
	repo, err := a.WT.ResolveRepo(rt.Context, directory)
	if err != nil {
		return endpoint, o, err
	}
	if err = meta.SetHome(plan.Session, directory, repo.Root); err != nil {
		return endpoint, o, err
	}
	a.WT.BindSessionHome(plan.Session, directory)
	o, err = a.reviewCheckpoint(o, "review-endpoint-intent", endpoint)
	return endpoint, o, err
}

func verifyReviewOwner(rt runtime.Runtime, child, op string) error {
	owner, err := rt.TmuxOutput("show-environment", "-t", "="+child, "ROAMI_LIFECYCLE_OPERATION")
	if err != nil || strings.TrimSpace(owner) != "ROAMI_LIFECYCLE_OPERATION="+op {
		return lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
	}
	return nil
}

func reviewEndpoint(rt runtime.Runtime, name, identity, kind string) (sessionreview.Endpoint, error) {
	actual, err := rt.SessionIdentity(name)
	if err != nil || actual == "" || actual != identity {
		return sessionreview.Endpoint{}, lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
	}
	out, err := rt.TmuxOutput("list-panes", "-s", "-t", "="+name, "-F", "#{pane_id}")
	pane := strings.TrimSpace(out)
	if err != nil || !strings.HasPrefix(pane, "%") || strings.ContainsAny(pane, "\r\n\t ") {
		return sessionreview.Endpoint{}, lifecycleFailure(fmt.Errorf("LIFECYCLE_REVIEW_NOT_READY"))
	}
	return sessionreview.Endpoint{Session: name, Identity: identity, Pane: pane, Agent: kind}, nil
}

func reviewPaneReady(rt runtime.Runtime, endpoint sessionreview.Endpoint) bool {
	out, err := rt.TmuxOutput("display-message", "-p", "-t", endpoint.Pane, "#{session_name}\t#{pane_pid}\t#{pane_in_mode}\t#{pane_dead}")
	fields := strings.Split(strings.TrimSpace(out), "\t")
	if err != nil || len(fields) != 4 || fields[0] != endpoint.Session || fields[2] != "0" || fields[3] != "0" {
		return false
	}
	pid, _ := strconv.Atoi(fields[1])
	if pid <= 1 {
		return false
	}
	kind, _ := registeredAgentInTree(pid, procChildren(), func(pid int) []string {
		if procStopped(pid) {
			return nil
		}
		return processArgv(pid)
	})
	if kind != endpoint.Agent {
		return false
	}
	screen, err := rt.TmuxOutput("capture-pane", "-p", "-t", endpoint.Pane)
	return err == nil && strings.TrimSpace(screen) != "" && !screenBusy(screen) && !sessionWaiting(screen)
}

const reviewReadyLine = "ROAMI_REVIEW_READY"

func reviewLaunchReady(rt runtime.Runtime, reviewer sessionreview.Endpoint) bool {
	if !reviewPaneReady(rt, reviewer) {
		return false
	}
	out, err := rt.TmuxOutput("capture-pane", "-p", "-t", reviewer.Pane)
	if err != nil {
		return false
	}
	for _, line := range strings.Split(out, "\n") {
		if strings.TrimSpace(strings.TrimLeft(waitClean(line), "●•◆")) == reviewReadyLine {
			return true
		}
	}
	return false
}

func (a *API) stopLifecycleReview(ctx context.Context, o life.Operation) error {
	if !o.Has("review-intent") {
		return nil
	}
	var plan reviewPlan
	if err := o.Receipt("review-intent", &plan); err != nil {
		return err
	}
	rt := lifecycleRuntime(ctx)
	if err := sessionreview.Open(rt).Interrupt(ctx, o.ResourceID, "creation_cancelled"); err != nil {
		return err
	}
	release, err := a.Lifecycle.Acquire(ctx, "resource:"+plan.Session, false)
	if err != nil {
		return err
	}
	defer release()
	identity, err := rt.SessionIdentity(plan.Session)
	if err != nil {
		return err
	}
	var proof memguard.PaneStopProof
	if o.Has("review-stop-intent") {
		if err = o.Receipt("review-stop-intent", &proof); err != nil {
			return err
		}
	}
	if identity != "" {
		if err = verifyReviewOwner(rt, plan.Session, o.ID); err != nil {
			return err
		}
		if o.Has("review-endpoint-intent") {
			var reviewer sessionreview.Endpoint
			if err = o.Receipt("review-endpoint-intent", &reviewer); err != nil || identity != reviewer.Identity {
				return lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
			}
		}
		if o.Has("review-launch-intent") && len(proof.Scopes) == 0 {
			proof, err = memguard.CapturePaneStopProof(rt.PanePIDs(plan.Session))
			if err != nil {
				return lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED: %w", err))
			}
			if _, err = a.reviewCheckpoint(o, "review-stop-intent", proof); err != nil {
				return err
			}
		}
	} else if o.Has("review-launch-intent") && len(proof.Scopes) == 0 {
		return lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED"))
	}
	if len(proof.Scopes) != 0 {
		if err = memguard.StopPaneScopes(ctx, proof); err != nil {
			return lifecycleFailure(fmt.Errorf("LIFECYCLE_STOP_UNCONFIRMED: %w", err))
		}
	}
	current, err := rt.SessionIdentity(plan.Session)
	if err != nil {
		return err
	}
	if current != "" {
		if current != identity {
			return lifecycleFailure(fmt.Errorf("LIFECYCLE_IDENTITY_CHANGED"))
		}
		if err = rt.Tmux("kill-session", "-t", "="+plan.Session); err != nil {
			return err
		}
	}
	meta := sessmeta.New(rt.HomeDir)
	meta.DataDir = rt.DataDir
	return meta.OnKill(plan.Session)
}

func reviewerPromptForPair(author, task string) string {
	return fmt.Sprintf("# Original task\n\n%s\n\n# Peer review\n\nYou are the reviewer. Acknowledge readiness with %s on a line of its own, then wait for a [review.request] from the paired author. Read the immutable patch at Read-only patch, use the original task as the review criteria, and leave the workspace unchanged. Send one verdict with concrete evidence. Substitute the exact round and full revision from the request. Use one of:\n\nroami session send %s '[review.changes_requested] rN rev=REVISION File:line, issue, evidence and suggested fix'\nroami session send %s '[review.approved] rN rev=REVISION What was checked and the result'\n\nAfter submitting, wait for the next request. Approval or round %d ends the review.", task, reviewReadyLine, author, author, sessionreview.MaxRounds)
}

func authorReviewAppendix(reviewer string, trigger string) string {
	first := "When your first verifiable version is ready, send it for review before closing your session."
	if trigger == "idle" {
		first = "The host submits the first version when you are idle and there are workspace changes. Keep your session open to receive the findings."
	}
	return fmt.Sprintf("\n\n# Peer review\n\nYour reviewer is the review session %s. %s After changes are requested, address or explain the findings, verify the new version and submit it again. The host records the exact workspace snapshot and sends the request.\n\nroami session send %s '[review.request] Summarize the changes and verification for this version'\n\nKeep the author session open while review is pending. Approval or %d rounds ends the review. Preserve unresolved findings at the round limit.", reviewer, first, reviewer, sessionreview.MaxRounds)
}
