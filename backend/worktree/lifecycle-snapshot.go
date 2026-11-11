package worktree

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

type LifecycleSnapshot struct {
	Fingerprint   string `json:"fingerprint"`
	FilesHash     string `json:"filesHash"`
	UntrackedHash string `json:"untrackedHash"`
	Head          string `json:"head"`
	Branch        string `json:"branch"`
	Clean         bool   `json:"clean"`
}

func (s *Service) Snapshot(ctx context.Context, path string) (string, error) {
	state, err := s.SnapshotState(ctx, path)
	return state.Fingerprint, err
}

type snapshotFileReader struct {
	ctx  context.Context
	file *os.File
}

func (r snapshotFileReader) Read(buffer []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.file.Read(buffer)
}

// Snapshot includes ignored files too: a late writer must not disappear under a force removal.
func (s *Service) SnapshotState(ctx context.Context, path string) (state LifecycleSnapshot, failure error) {
	path = canonical(path)
	hash := sha256.New()
	filesHash := sha256.New()
	untrackedHash := sha256.New()
	content := sha256.New()
	buffer := make([]byte, 32*1024)
	trackedOutput, err := git(ctx, path, "ls-files", "-z")
	if err != nil {
		return state, err
	}
	tracked := map[string]bool{}
	trackedDirs := map[string]bool{}
	for _, name := range strings.Split(trackedOutput, "\x00") {
		if name == "" {
			continue
		}
		tracked[name] = true
		for dir := filepath.Dir(name); dir != "." && dir != "/"; dir = filepath.Dir(dir) {
			trackedDirs[dir] = true
		}
	}
	for _, target := range []string{path, filepath.Join(path, ".git")} {
		info, e := os.Lstat(target)
		if e != nil {
			return state, e
		}
		if stat, ok := info.Sys().(*syscall.Stat_t); ok {
			fmt.Fprintf(hash, "%d:%d\x00", stat.Dev, stat.Ino)
		}
	}
	for _, args := range [][]string{{"rev-parse", "--absolute-git-dir"}, {"rev-parse", "HEAD"}, {"symbolic-ref", "HEAD"}, {"diff", "--binary", "HEAD", "--"}, {"status", "--porcelain=v1", "-z", "--untracked-files=all"}} {
		var out string
		var err error
		if args[0] == "symbolic-ref" {
			out, err = lifecycleBranch(ctx, path)
		} else {
			out, err = git(ctx, path, args...)
		}
		if err != nil {
			return state, err
		}
		fmt.Fprintf(hash, "%q\x00", out)
		if args[0] == "status" {
			state.Clean = strings.TrimSpace(out) == ""
		}
		if args[0] == "symbolic-ref" {
			state.Branch = strings.TrimSpace(out)
		}
		if len(args) > 1 && args[0] == "rev-parse" && args[1] == "HEAD" {
			state.Head = strings.TrimSpace(out)
		}
		if len(args) > 1 && args[1] == "--absolute-git-dir" {
			info, e := os.Stat(strings.TrimSpace(out))
			if e != nil {
				return state, e
			}
			if stat, ok := info.Sys().(*syscall.Stat_t); ok {
				fmt.Fprintf(hash, "%d:%d\x00", stat.Dev, stat.Ino)
			}
		}
	}
	err = filepath.WalkDir(path, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		rel, e := filepath.Rel(path, p)
		if e != nil {
			return e
		}
		if rel == ".git" {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if rel == "." {
			return nil
		}
		var entry io.Writer = io.MultiWriter(hash, filesHash)
		if !tracked[filepath.ToSlash(rel)] && (!d.IsDir() || !trackedDirs[rel]) {
			entry = io.MultiWriter(hash, filesHash, untrackedHash)
		}
		info, e := d.Info()
		if e != nil {
			return e
		}
		fmt.Fprintf(entry, "%q:%d:%d:%d\x00", rel, info.Mode(), info.Size(), info.ModTime().UnixNano())
		if stat, ok := info.Sys().(*syscall.Stat_t); ok {
			fmt.Fprintf(entry, "%d:%d\x00", stat.Dev, stat.Ino)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			target, e := os.Readlink(p)
			if e != nil {
				return e
			}
			fmt.Fprintf(entry, "%q", target)
		}
		if info.Mode().IsRegular() {
			file, e := os.Open(p)
			if e != nil {
				return e
			}
			content.Reset()
			// Hide File.WriteTo so CopyBuffer reuses one buffer for the entire tree.
			_, readErr := io.CopyBuffer(content, snapshotFileReader{ctx: ctx, file: file}, buffer)
			after, statErr := file.Stat()
			_ = file.Close()
			if readErr != nil {
				return readErr
			}
			if statErr != nil {
				return statErr
			}
			if !os.SameFile(info, after) || info.Size() != after.Size() || !info.ModTime().Equal(after.ModTime()) {
				return errf("LIFECYCLE_WORKSPACE_CHANGED", "file changed during inspection")
			}
			fmt.Fprintf(entry, "%x\x00", content.Sum(nil))
		}
		return nil
	})
	if err != nil {
		return state, err
	}
	state.Fingerprint = fmt.Sprintf("%x", hash.Sum(nil))
	state.FilesHash = fmt.Sprintf("%x", filesHash.Sum(nil))
	state.UntrackedHash = fmt.Sprintf("%x", untrackedHash.Sum(nil))
	return state, nil
}

func (s *Service) RemovalComplete(ctx context.Context, repoDirectory, path string) (bool, error) {
	if _, err := os.Lstat(path); err == nil {
		return false, nil
	} else if !os.IsNotExist(err) {
		return false, err
	}
	repo, err := s.ResolveRepo(ctx, repoDirectory)
	if err != nil {
		return false, err
	}
	out, err := git(ctx, repo.Root, "worktree", "list", "--porcelain")
	if err != nil {
		return false, err
	}
	for _, line := range strings.Split(out, "\n") {
		if registered, ok := strings.CutPrefix(line, "worktree "); ok && canonical(registered) == canonical(path) {
			return false, nil
		}
	}
	return true, nil
}

func (s *Service) LifecycleDetails(ctx context.Context, path string) (Worktree, error) {
	repo, err := s.ResolveRepo(ctx, path)
	if err != nil {
		return Worktree{}, err
	}
	if canonical(path) == repo.Root || !s.isRegisteredWorktree(ctx, repo, canonical(path)) {
		return Worktree{}, errf("LIFECYCLE_WORKSPACE_PROTECTED", "not a linked worktree")
	}
	w := Worktree{Path: canonical(path)}
	w.Branch, err = lifecycleBranch(ctx, path)
	if err != nil {
		return w, err
	}
	w.Branch = strings.TrimPrefix(w.Branch, "refs/heads/")
	w.Head, err = s.Head(ctx, path)
	if err != nil {
		return w, err
	}
	w.Base, _ = git(ctx, path, "config", "--worktree", "--get", "roam.baseref")
	w.CreatedBy, _ = git(ctx, path, "config", "--worktree", "--get", "roam.createdby")
	adopted, _ := git(ctx, path, "config", "--worktree", "--get", "roam.adopted")
	w.Adopted = strings.TrimSpace(adopted) == "1"
	w.External = w.CreatedBy != "roam"
	return w, nil
}

func lifecycleBranch(ctx context.Context, path string) (string, error) {
	branch, err := git(ctx, path, "symbolic-ref", "--quiet", "HEAD")
	var exit *exec.ExitError
	if errors.As(err, &exit) && exit.ExitCode() == 1 {
		return "", nil
	}
	return branch, err
}

func (s *Service) LifecycleOwner(ctx context.Context, path string) (string, error) {
	owner, err := git(ctx, path, "config", "--worktree", "--get", "roam.lifecycle-operation")
	return strings.TrimSpace(owner), err
}

// DeleteLifecycleBranch only removes the exact branch tip recorded before directory removal.
func (s *Service) DeleteLifecycleBranch(ctx context.Context, dir, branch, head string, force bool) error {
	repo, err := s.ResolveRepo(ctx, dir)
	if err != nil {
		return err
	}
	unlock, err := s.lock(ctx, repo)
	if err != nil {
		return err
	}
	defer unlock()
	out, e := git(ctx, repo.Root, "for-each-ref", "--format=%(objectname)", "refs/heads/"+branch)
	if e != nil {
		return e
	}
	if strings.TrimSpace(out) == "" {
		return nil
	}
	if strings.TrimSpace(out) != head {
		return errf("LIFECYCLE_WORKSPACE_CHANGED", "branch tip changed after cleanup")
	}
	flag := "-d"
	if force {
		flag = "-D"
	}
	out, e = git(ctx, repo.Root, "branch", flag, "--", branch)
	if e != nil {
		return errf("BRANCH_NOT_MERGED", "%s", out)
	}
	return nil
}

func (s *Service) LifecycleCommitMatches(ctx context.Context, path, previousHead, message string) (bool, error) {
	out, err := git(ctx, path, "log", "-1", "--format=%P%n%s")
	if err != nil {
		return false, err
	}
	parent, subject, ok := strings.Cut(out, "\n")
	return ok && strings.TrimSpace(parent) == previousHead && subject == message, nil
}
