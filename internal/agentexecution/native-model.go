package agentexecution

import (
	"context"

	"github.com/ybz21/Roami/internal/agentproviders"
)

func (s Service) nativeModelID(ctx context.Context, kind, model string) string {
	if kind != "claude" || model == "" {
		return model
	}
	view, err := agentproviders.NewStore(s.Runtime.DataDir).View(ctx, kind)
	if err != nil {
		return model
	}
	return agentproviders.NativeModelID(kind, model, view)
}
