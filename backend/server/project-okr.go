package server

import (
	"context"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/api"
)

type projectOKRLifecycle struct {
	cancel context.CancelFunc
	done   chan struct{}
}

var projectOKRCollectors sync.Map

func startProjectOKRCollector(engine *gin.Engine, handler *api.API, parent context.Context) {
	if parent == nil {
		parent = context.Background()
	}
	ctx, cancel := context.WithCancel(parent)
	worker := &projectOKRLifecycle{cancel: cancel, done: make(chan struct{})}
	projectOKRCollectors.Store(engine, worker)
	go func() {
		defer close(worker.done)
		defer projectOKRCollectors.Delete(engine)
		defer cancel()
		handler.ProjectOKRCollector(ctx)
	}()
}

// Close cancels and joins background collection for this engine. Managed SQLite connections
// remain owned by the platform pool, which may also serve another engine in this process.
func Close(engine *gin.Engine) {
	if value, ok := projectOKRCollectors.LoadAndDelete(engine); ok {
		worker := value.(*projectOKRLifecycle)
		worker.cancel()
		<-worker.done
	}
}
