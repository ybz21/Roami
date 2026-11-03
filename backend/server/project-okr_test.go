package server

import (
	"context"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestCloseCancelsAndJoinsProjectOKRCollector(t *testing.T) {
	engine := gin.New()
	ctx, cancel := context.WithCancel(context.Background())
	worker := &projectOKRLifecycle{cancel: cancel, done: make(chan struct{})}
	projectOKRCollectors.Store(engine, worker)
	exited := make(chan struct{})
	go func() { <-ctx.Done(); close(exited); close(worker.done) }()
	Close(engine)
	select {
	case <-exited:
	case <-time.After(time.Second):
		t.Fatal("close did not join collector")
	}
	if _, ok := projectOKRCollectors.Load(engine); ok {
		t.Fatal("closed engine retained")
	}
	Close(engine)
}
