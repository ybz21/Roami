package worktree

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func BenchmarkLifecycleSnapshotIgnoredFiles(b *testing.B) {
	ctx := context.Background()
	repo := b.TempDir()
	for _, args := range [][]string{{"init", "-b", "main"}, {"-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "fixture"}} {
		if out, err := git(ctx, repo, args...); err != nil {
			b.Fatalf("git: %v %s", err, out)
		}
	}
	if err := os.WriteFile(filepath.Join(repo, ".gitignore"), []byte("dependencies/\n"), 0600); err != nil {
		b.Fatal(err)
	}
	directory := filepath.Join(repo, "dependencies")
	if err := os.Mkdir(directory, 0700); err != nil {
		b.Fatal(err)
	}
	const files, size = 2000, 1024
	content := make([]byte, size)
	for i := range files {
		if err := os.WriteFile(filepath.Join(directory, fmt.Sprintf("file-%04d", i)), content, 0600); err != nil {
			b.Fatal(err)
		}
	}
	service := New("", nil)
	b.SetBytes(files * size)
	b.ReportAllocs()
	b.ResetTimer()
	for range b.N {
		if _, err := service.SnapshotState(ctx, repo); err != nil {
			b.Fatal(err)
		}
	}
}
