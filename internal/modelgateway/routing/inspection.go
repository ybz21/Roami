package routing

import (
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/catalog"
)

type ChannelStatus struct {
	SourceID     string   `json:"sourceId"`
	Model        string   `json:"model"`
	Account      string   `json:"account"`
	Kind         string   `json:"kind"`
	Ready        bool     `json:"ready"`
	Remaining    *float64 `json:"remaining"`
	ResetAt      *int64   `json:"resetAt"`
	ExpiresAt    *int64   `json:"expiresAt"`
	RestUntil    *int64   `json:"restUntil"`
	MeasuredAt   *int64   `json:"measuredAt"`
	RecentTokens int64    `json:"recentTokens"`
}

type MemberStatus struct {
	catalog.ModelCandidate
	Block   string `json:"block,omitempty"`
	Context int    `json:"context,omitempty"`
}

func (c *Choice) Inspect() (int, []ChannelStatus, []MemberStatus) {
	c.selector.mu.Lock()
	defer c.selector.mu.Unlock()
	memory := c.selector.memory(c.model, c.anchors)
	now := c.now()
	rows := []ChannelStatus{}
	available := 0
	for _, target := range rankRouteTargets(c.model.Strategy, c.targets, now, memory) {
		node := c.nodes[target.ID]
		ready := availableTarget(target, now)
		if ready {
			available++
		}
		source, native, account := catalog.GroupSource, "", ""
		if node.leaf != nil {
			source, native, account = node.leaf.Candidate.SourceID, node.leaf.Candidate.Model, node.leaf.Account
		} else {
			native = node.child.model.ID
		}
		var reset, expiry *int64
		if !target.Quota.Reset.IsZero() {
			value := target.Quota.Reset.UnixMilli()
			reset = &value
		}
		if at := firstExpiry(target.Quota); !at.IsZero() {
			value := at.UnixMilli()
			expiry = &value
		}
		var rest *int64
		if target.Channel.RestUntil.After(now) {
			value := target.Channel.RestUntil.UnixMilli()
			rest = &value
		}
		rows = append(rows, ChannelStatus{
			SourceID: source, Model: native, Account: AccountLabel(account), Kind: target.Kind,
			Ready: ready, Remaining: target.Quota.Remaining, ResetAt: reset, ExpiresAt: expiry,
			RestUntil: rest, MeasuredAt: optionalMilliseconds(target.Channel.Measured),
			RecentTokens: target.Channel.Input + target.Channel.Output,
		})
	}
	members := make([]MemberStatus, 0, len(c.model.Candidates))
	for _, candidate := range c.model.Candidates {
		members = append(members, MemberStatus{candidate, c.blocks[candidate], c.contexts[candidate]})
	}
	return available, rows, members
}

func optionalMilliseconds(value time.Time) *int64 {
	if value.IsZero() {
		return nil
	}
	stamp := value.UnixMilli()
	return &stamp
}
