package service

import (
	"context"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/routing"
	"github.com/ybz21/Roami/internal/modelgateway/storage"
)

func (h *Handler) newRoutingChoice(ctx context.Context, catalog ModelCatalog, model CatalogModel, request routing.Requirements, inspect bool) (*routing.Choice, error) {
	var inspectSource func(context.Context, ModelSource, string) routing.DirectoryEvidence
	if h.Catalog != nil {
		inspectSource = func(ctx context.Context, source ModelSource, revision string) routing.DirectoryEvidence {
			entry := h.routingSourceDirectory(ctx, source, revision)
			return routing.DirectoryEvidence{Details: entry.Details, ObservedAt: entry.ObservedAt, Problem: entry.Problem}
		}
	}
	return h.routing.Choose(ctx, routing.Snapshot{Models: catalog.Models, Sources: catalog.Sources, Revision: catalog.Revision},
		model, request, inspect, routing.Dependencies{
			Configuration: h.state.accounting.Configuration, Now: h.state.now, Plugins: h.Plugins,
			Anchors: storage.RouteAnchors{DB: h.state.db}, InspectSource: inspectSource,
		})
}

func (h *Handler) restRoute(leaf routing.Leaf, model CatalogModel, status int, retry time.Duration) {
	h.routing.Rest(leaf, model, status, retry, h.state.now())
}
