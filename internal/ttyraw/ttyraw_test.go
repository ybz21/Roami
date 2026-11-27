package ttyraw

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestPipeIsNotTerminalAndWatchExits(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	defer r.Close()
	defer w.Close()

	if IsTerminal(r.Fd()) {
		t.Fatalf("pipe should not report as terminal")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	done := make(chan struct{})
	go func() {
		defer close(done)
		WatchResize(ctx, r.Fd(), func(_, _ uint16) {})
	}()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatalf("WatchResize did not stop after context cancel")
	}
}
