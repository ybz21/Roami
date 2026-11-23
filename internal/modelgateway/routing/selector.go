package routing

import (
	"context"
	"time"

	"github.com/ybz21/Roami/internal/agentproviders"
	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	"github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelplugins"
)

type AnchorStore interface {
	Load(modelID string) (fingerprint, anchor string)
	Save(modelID, fingerprint, anchor string) error
}

type Dependencies struct {
	Configuration func() (accounting.Configuration, error)
	Now           func() time.Time
	Anchors       AnchorStore
	Plugins       *modelplugins.Manager
	InspectSource func(context.Context, catalog.ModelSource, string) DirectoryEvidence
}

type Snapshot struct {
	Sources  []catalog.ModelSource
	Models   []catalog.CatalogModel
	Revision string
}

type DirectoryEvidence struct {
	Details    []agentproviders.SourceModelDetail
	ObservedAt time.Time
	Problem    string
}

func (s *Selector) InvalidateQuota(source, account string) {
	s.quota.invalidate(source, account)
}
