package worktree

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"strings"
	"time"
)

// PreparedBase is opaque outside this package; callers can share a freshly fetched
// snapshot across race contestants without accepting an OID from the HTTP client.
type PreparedBase struct{ repo, base, remote, remoteBranch, oid string }

func (s *Service) PrepareBase(ctx context.Context, dir, base, remote string) (PreparedBase, error) {
	repo, e := s.ResolveRepo(ctx, dir)
	if e != nil {
		return PreparedBase{}, e
	}
	release, e := s.lock(repo)
	if e != nil {
		return PreparedBase{}, e
	}
	defer release()
	if base == "" {
		base = s.defaultBase(ctx, repo)
	}
	return s.freshBase(ctx, repo, base, remote)
}
func (s *Service) CreateFromBase(ctx context.Context, req CreateReq, prepared PreparedBase) (CreateResp, error) {
	return s.create(ctx, req, &prepared)
}

func (s *Service) freshBase(ctx context.Context, repo Repo, base, remote string) (PreparedBase, error) {
	label := base
	if remote == "" && base != "" {
		if upstream, e := git(ctx, repo.Root, "config", "--get", "branch."+base+".remote"); e == nil && strings.TrimSpace(upstream) != "." {
			remote = strings.TrimSpace(upstream)
			if merge, e := git(ctx, repo.Root, "config", "--get", "branch."+base+".merge"); e == nil {
				base = strings.TrimPrefix(strings.TrimSpace(merge), "refs/heads/")
			}
		}
	}
	if remote == "" {
		if _, e := git(ctx, repo.Root, "remote", "get-url", "origin"); e == nil {
			remote = "origin"
		} else {
			names, e := git(ctx, repo.Root, "remote")
			if e != nil {
				return PreparedBase{}, errf("REMOTE_UNRESOLVED", "cannot list remotes")
			}
			all := strings.Fields(names)
			if len(all) == 0 {
				if base == "" {
					base = s.defaultBase(ctx, repo)
				}
				if _, e := git(ctx, repo.Root, "check-ref-format", "refs/heads/"+base); e != nil {
					return PreparedBase{}, errf("BAD_BASE", "invalid local branch %q", base)
				}
				oid, e := git(ctx, repo.Root, "rev-parse", "--verify", "--end-of-options", "refs/heads/"+base+"^{commit}")
				if e != nil {
					return PreparedBase{}, errf("BAD_BASE", "cannot resolve local branch %q", base)
				}
				return PreparedBase{repo: repo.Root, base: base, oid: strings.TrimSpace(oid)}, nil
			}
			if len(all) != 1 {
				return PreparedBase{}, errf("REMOTE_REQUIRED", "select a remote before creating a task worktree")
			}
			remote = all[0]
		}
	}
	if _, e := git(ctx, repo.Root, "remote", "get-url", remote); e != nil {
		return PreparedBase{}, errf("REMOTE_UNRESOLVED", "unknown remote %q", remote)
	}
	if strings.HasPrefix(remote, "-") {
		return PreparedBase{}, errf("BAD_BASE", "invalid remote")
	}
	if base == "" {
		headCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
		defer cancel()
		out, e := git(headCtx, repo.Root, "ls-remote", "--symref", "--", remote, "HEAD")
		if e != nil {
			return PreparedBase{}, errf("FETCH_FAILED", "cannot resolve remote HEAD: %s", out)
		}
		for _, line := range strings.Split(out, "\n") {
			if strings.HasPrefix(line, "ref: refs/heads/") {
				ref, _, _ := strings.Cut(strings.TrimPrefix(line, "ref: refs/heads/"), "\t")
				base = ref
				break
			}
		}
		label = base
	}
	if base == "" || strings.HasPrefix(base, "-") {
		return PreparedBase{}, errf("BASE_UNRESOLVED", "cannot determine remote default branch")
	}
	if _, e := git(ctx, repo.Root, "check-ref-format", "refs/heads/"+base); e != nil {
		return PreparedBase{}, errf("BAD_BASE", "invalid branch %q", base)
	}
	var random [16]byte
	if _, e := rand.Read(random[:]); e != nil {
		return PreparedBase{}, e
	}
	ref := "refs/roami/prepares/" + hex.EncodeToString(random[:])
	defer func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_, _ = git(cleanup, repo.Root, "update-ref", "-d", ref)
	}()
	fctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	if out, e := git(fctx, repo.Root, "fetch", "--no-tags", "--no-write-fetch-head", "--", remote, "+refs/heads/"+base+":"+ref); e != nil {
		return PreparedBase{}, errf("FETCH_FAILED", "cannot refresh %s/%s: %s", remote, base, out)
	}
	oid, e := git(ctx, repo.Root, "rev-parse", "--verify", "--end-of-options", ref+"^{commit}")
	if e != nil {
		return PreparedBase{}, errf("BAD_BASE", "fetched ref is not a commit")
	}
	oid = strings.TrimSpace(oid)
	if out, e := git(ctx, repo.Root, "update-ref", "refs/remotes/"+remote+"/"+base, oid); e != nil {
		return PreparedBase{}, errf("GIT_ERROR", "update tracking ref: %s", out)
	}
	return PreparedBase{repo: repo.Root, base: label, remote: remote, remoteBranch: base, oid: oid}, nil
}
