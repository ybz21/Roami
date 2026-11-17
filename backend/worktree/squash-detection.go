package worktree

import (
	"context"
	"os/exec"
	"strings"
)

// Multi-commit squashes preserve the combined patch, not each original commit's patch-id.
func detectCombinedSquash(ctx context.Context, w *Worktree, target string) (string, bool) {
	if w.CommittedAhead < 2 || w.AheadUnique == 0 {
		return "", false
	}
	base, err := git(ctx, w.Path, "merge-base", "HEAD", target)
	if err != nil || strings.Contains(base, "\n") {
		return "", false
	}
	options := []string{
		"--no-ext-diff", "--no-textconv", "--no-renames", "--no-color", "--no-relative",
		"--full-index", "--binary", "--src-prefix=a/", "--dst-prefix=b/",
		"--diff-algorithm=myers", "--unified=3", "--inter-hunk-context=0",
	}
	combined, err := patchIDs(ctx, w.Path, append(append([]string{"diff"}, options...), base, "HEAD", "--")...)
	if err != nil || len(combined) != 1 {
		return "", false
	}
	// Search only target commits since divergence; later unrelated commits need not match HEAD's tree.
	landed, err := patchIDs(ctx, w.Path, append(append([]string{"log", "--no-merges", "--format=commit %H", "-p"}, options...), base+".."+target, "--")...)
	if err != nil {
		return "", false
	}
	for _, id := range landed {
		if id == combined[0] {
			w.AheadUnique = 0
			return "squash", true
		}
	}
	return "", false
}

// Stream patches into Git so large target histories do not accumulate diff text in memory.
func patchIDs(ctx context.Context, path string, args ...string) ([]string, error) {
	producer := exec.CommandContext(ctx, "git", append([]string{"-C", path}, args...)...)
	producer.Env = append(scrubGitEnv(), "GIT_TERMINAL_PROMPT=0", "LC_ALL=C")
	patches, err := producer.StdoutPipe()
	if err != nil {
		return nil, err
	}
	defer patches.Close()
	consumer := exec.CommandContext(ctx, "git", "-C", path, "patch-id", "--stable")
	consumer.Env = producer.Env
	consumer.Stdin = patches
	if err := producer.Start(); err != nil {
		return nil, err
	}
	out, consumerErr := consumer.Output()
	// A failed consumer must unblock the producer before waiting for it.
	patches.Close()
	producerErr := producer.Wait()
	if consumerErr != nil {
		return nil, consumerErr
	}
	if producerErr != nil {
		return nil, producerErr
	}
	var ids []string
	for _, line := range strings.Split(string(out), "\n") {
		if fields := strings.Fields(line); len(fields) == 2 {
			ids = append(ids, fields[0])
		}
	}
	return ids, nil
}
