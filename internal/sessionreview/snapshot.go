package sessionreview

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/ybz21/Roami/internal/gitcontext"
)

var ErrNoChanges = errors.New("no workspace changes to review")
var ErrWorkspaceChanged = errors.New("workspace changed before review could start")
var ErrAlreadyReviewed = errors.New("this workspace version was already reviewed")

func git(ctx context.Context, directory string, args ...string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = directory
	cmd.Env = gitcontext.ForDirectory(os.Environ())
	return cmd
}

func Baseline(ctx context.Context, directory string) (string, error) {
	out, err := git(ctx, directory, "rev-parse", "--verify", "HEAD^{commit}").Output()
	return strings.TrimSpace(string(out)), err
}

func WorkspaceSignalPaths(ctx context.Context, directory string) ([]string, error) {
	out, err := git(ctx, directory, "rev-parse", "--absolute-git-dir").Output()
	if err != nil {
		return nil, err
	}
	gitDir := strings.TrimSuffix(string(out), "\n")
	return []string{directory, filepath.Join(gitDir, "HEAD"), filepath.Join(gitDir, "index")}, nil
}

func writePatch(ctx context.Context, p Pair, w io.Writer) error {
	files, err := git(ctx, p.Directory, "ls-files", "-z", "--others", "--exclude-standard", "--").Output()
	if err != nil {
		return err
	}
	cmd := git(ctx, p.Directory, "diff", "--binary", "--no-ext-diff", "--no-textconv", p.Base, "--")
	cmd.Stdout = w
	if err := cmd.Run(); err != nil {
		return err
	}
	for _, raw := range bytes.Split(files, []byte{0}) {
		if len(raw) == 0 {
			continue
		}
		cmd := git(ctx, p.Directory, "diff", "--no-index", "--binary", "--no-ext-diff", "--no-textconv", "--", os.DevNull, string(raw))
		cmd.Stdout = w
		var status *exec.ExitError
		if err := cmd.Run(); err != nil && (!errors.As(err, &status) || status.ExitCode() != 1) {
			return err
		}
	}
	return nil
}

// WorkspaceVersion returns an empty version when the workspace matches the baseline.
func WorkspaceVersion(ctx context.Context, p Pair) (string, error) {
	digest := sha256.New()
	if err := writePatch(ctx, p, digest); err != nil {
		return "", err
	}
	return patchVersion(digest.Sum(nil)), nil
}

var emptyPatchDigest = sha256.Sum256(nil)

func patchVersion(sum []byte) string {
	if bytes.Equal(sum, emptyPatchDigest[:]) {
		return ""
	}
	return fmt.Sprintf("%x", sum)
}

func (s *Store) snapshot(ctx context.Context, p Pair, round int, expected string) (string, error) {
	digest := sha256.New()
	var version string
	name := filepath.Base(s.SnapshotPath(p.Author.Session, round))
	err := replaceFile(s.ownerDir(p.Author.Session), name, func(f *os.File) error {
		if err := writePatch(ctx, p, io.MultiWriter(f, digest)); err != nil {
			return err
		}
		version = patchVersion(digest.Sum(nil))
		if expected != "" && expected != version {
			return ErrWorkspaceChanged
		}
		if version == "" {
			return ErrNoChanges
		}
		if p.Reviewed(version) {
			return ErrAlreadyReviewed
		}
		return f.Chmod(0400)
	})
	if err != nil {
		return "", err
	}
	return version, nil
}

func (s *Store) SnapshotPath(author string, round int) string {
	return filepath.Join(s.ownerDir(author), fmt.Sprintf("round-%d.diff", round))
}
