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

func (s *Store) snapshot(ctx context.Context, p Pair, round int) (string, error) {
	files, err := git(ctx, p.Directory, "ls-files", "-z", "--others", "--exclude-standard", "--").Output()
	if err != nil {
		return "", err
	}
	digest := sha256.New()
	name := fmt.Sprintf("round-%d.diff", round)
	err = replaceFile(s.ownerDir(p.Author.Session), name, func(f *os.File) error {
		w := io.MultiWriter(f, digest)
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
		size, err := f.Seek(0, io.SeekCurrent)
		if err != nil {
			return err
		}
		if size == 0 {
			return ErrNoChanges
		}
		return f.Chmod(0400)
	})
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%x", digest.Sum(nil)), nil
}

func (s *Store) SnapshotPath(author string, round int) string {
	return filepath.Join(s.ownerDir(author), fmt.Sprintf("round-%d.diff", round))
}
