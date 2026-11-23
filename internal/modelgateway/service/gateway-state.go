package service

import (
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	"github.com/ybz21/Roami/internal/modelgateway/storage"
	metadb "github.com/ybz21/Roami/internal/storage"
)

type gatewayState struct {
	accounting *accounting.Ledger
	paths      metadb.Paths
	db         *metadb.DB
	now        func() time.Time
}

func openState(paths metadb.Paths) (*gatewayState, error) {
	db, err := storage.Open(paths)
	if err != nil {
		return nil, err
	}
	state := &gatewayState{paths: paths, db: db, now: time.Now}
	state.accounting = accounting.New(db, func() time.Time { return state.now() })
	return state, nil
}

type gatewayKeyContext struct{}
