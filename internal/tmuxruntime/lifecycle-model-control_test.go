package runtime

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestExclusivePaneInputFencesSessionAndPaneTargets(t *testing.T) {
	root := t.TempDir()
	rt := Runtime{HomeDir: root, DataDir: root}
	err := rt.WithExclusivePaneInput("bound", "%7", func(scoped Runtime) error {
		for _, target := range []string{"=bound:", "%7"} {
			release, err := scoped.InputLease(target)
			if err != nil {
				t.Fatal(err)
			}
			release()
			wait, cancel := context.WithTimeout(context.Background(), 40*time.Millisecond)
			other := rt
			other.Context = wait
			release, err = other.InputLease(target)
			cancel()
			if err == nil {
				release()
			}
			if !errors.Is(err, context.DeadlineExceeded) {
				t.Fatalf("concurrent input for %q got %v", target, err)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	release, err := rt.InputLease("=bound:")
	if err != nil {
		t.Fatal(err)
	}
	release()
}
