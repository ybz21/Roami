package routing

import (
	"context"
	"errors"
	"net/http"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	"github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelplugins"
)

const MaxSourceAccounts = 64

func PluginSignedIn(provider modelplugins.Provider) bool {
	return provider.SignedIn && !modelplugins.DesktopUnavailable(provider.ID) && !modelplugins.DesktopAppMissing(provider.ID)
}

type sourceRouteFacts struct {
	source    catalog.ModelSource
	plugin    modelplugins.Provider
	quotas    map[string]modelplugins.Quota
	valid     map[string]bool
	directory DirectoryEvidence
}
type Leaf struct {
	Candidate          catalog.ModelCandidate
	Account, ChannelID string
	Ancestors          []string
	Free               bool
	PricingRevision    string
	ProviderStrategy   string
}
type routingNode struct {
	target routeTarget
	leaf   *Leaf
	child  *Choice
}
type Choice struct {
	selector              *Selector
	now                   func() time.Time
	anchors               AnchorStore
	model                 catalog.CatalogModel
	nodes                 map[string]*routingNode
	targets               []routeTarget
	blocks                map[catalog.ModelCandidate]string
	skips                 map[string]int
	contexts              map[catalog.ModelCandidate]int
	ordered               []routeTarget
	cursor                int
	initialized, reserved bool
	providersReserved     map[string]bool
}

func (s *Selector) routingFacts(ctx context.Context, snapshot Snapshot, model catalog.CatalogModel, inspect bool, deps Dependencies) (map[string]*sourceRouteFacts, error) {
	needed := map[string]bool{}
	byModel := map[string]catalog.CatalogModel{}
	for _, m := range snapshot.Models {
		byModel[m.ID] = m
	}
	var collect func(catalog.CatalogModel, int) error
	collect = func(m catalog.CatalogModel, depth int) error {
		if depth > 8 {
			return errors.New("MODEL_ROUTE_CYCLE")
		}
		for _, candidate := range m.Candidates {
			if candidate.SourceID == catalog.GroupSource {
				child, ok := byModel[candidate.Model]
				if !ok {
					return errors.New("INVALID_MODEL_CATALOG")
				}
				if err := collect(child, depth+1); err != nil {
					return err
				}
			} else {
				needed[candidate.SourceID] = needed[candidate.SourceID] || inspect || m.RequireTools || m.MinContext > 0
			}
		}
		return nil
	}
	if err := collect(model, 0); err != nil {
		return nil, err
	}
	facts := map[string]*sourceRouteFacts{}
	pluginSources := map[string]modelplugins.Source{}
	for _, source := range snapshot.Sources {
		if _, ok := needed[source.ID]; !ok {
			continue
		}
		value := &sourceRouteFacts{source: source, quotas: map[string]modelplugins.Quota{}, valid: map[string]bool{}}
		if source.PluginSourceID != "" && deps.Plugins != nil {
			pluginSource, err := deps.Plugins.ReadSource(source.PluginSourceID)
			if err == nil {
				value.plugin, _ = deps.Plugins.CachedProvider(pluginSource)
				pluginSources[source.ID] = pluginSource
			}
		}
		facts[source.ID] = value
	}
	var mu sync.Mutex
	var wait sync.WaitGroup
	gate := make(chan struct{}, 8)
	for id, value := range facts {
		if !needed[id] || value.source.PluginSourceID != "" || deps.InspectSource == nil {
			continue
		}
		wait.Add(1)
		go func(fact *sourceRouteFacts) {
			defer wait.Done()
			select {
			case gate <- struct{}{}:
				defer func() { <-gate }()
			case <-ctx.Done():
				return
			}
			fact.directory = deps.InspectSource(ctx, fact.source, snapshot.Revision)
		}(value)
	}
	for id, value := range facts {
		if !value.plugin.Usage || len(value.plugin.Accounts) > MaxSourceAccounts {
			continue
		}
		for _, account := range value.plugin.Accounts {
			wait.Add(1)
			go func(id string, source modelplugins.Source, account string) {
				defer wait.Done()
				select {
				case gate <- struct{}{}:
					defer func() { <-gate }()
				case <-ctx.Done():
					return
				}
				quota, valid := s.quota.read(ctx, deps.Plugins, source, account)
				mu.Lock()
				current := facts[id]
				current.quotas[account] = quota
				current.valid[account] = valid
				mu.Unlock()
			}(id, pluginSources[id], account.Key)
		}
	}
	wait.Wait()
	return facts, ctx.Err()
}

// The provider list is a union; it cannot prove each account has the same pricing.
func AccountPricingModel(model *modelplugins.Model, accounts int) *modelplugins.Model {
	if model == nil || accounts <= 1 {
		return model
	}
	copy := *model
	copy.Free = false
	copy.Rate = 0
	return &copy
}

func routeCapabilityBlock(model catalog.CatalogModel, advertised *modelplugins.Model) string {
	if model.RequireTools && (advertised == nil || !advertised.Tools) {
		return "tools"
	}
	if model.MinContext > 0 && (advertised == nil || advertised.Context < model.MinContext) {
		return "context"
	}
	return ""
}

func routeAllowed(model catalog.CatalogModel, candidate catalog.ModelCandidate, pluginModel *modelplugins.Model, quota routingQuota, pricing accounting.PricingConfig) bool {
	if !model.IsEnabled() || routeCapabilityBlock(model, pluginModel) != "" {
		return false
	}
	if !model.FreeOnly {
		return true
	}
	rule, explicit := pricing.SourceRule(candidate.SourceID, candidate.Model)
	if explicit {
		switch rule.Mode {
		case "free":
			return rule.Confirmed
		case "quota":
			return model.AllowPlan && quota.Known && quota.Remaining != nil && *quota.Remaining > 0
		default:
			return false
		}
	}
	return pluginModel != nil && (pluginModel.Free || model.AllowPlan && pluginModel.Rate > 0 && quota.Known && quota.Remaining != nil && *quota.Remaining > 0)
}
func (s *Selector) Choose(ctx context.Context, snapshot Snapshot, model catalog.CatalogModel, requiredProtocol string, inspect bool, deps Dependencies) (*Choice, error) {
	facts, err := s.routingFacts(ctx, snapshot, model, inspect, deps)
	if err != nil {
		return nil, err
	}
	config, err := deps.Configuration()
	if err != nil {
		return nil, err
	}
	priceRevision := accounting.PricingRevision(config)
	now := deps.Now()
	byID := map[string]catalog.CatalogModel{}
	for _, m := range snapshot.Models {
		byID[m.ID] = m
	}
	count := 0
	s.mu.Lock()
	defer s.mu.Unlock()
	var build func(catalog.CatalogModel, int, bool) (*Choice, error)
	build = func(m catalog.CatalogModel, depth int, freeOnly bool) (*Choice, error) {
		if depth > 8 {
			return nil, errors.New("MODEL_ROUTE_CYCLE")
		}
		configured := m
		if freeOnly {
			m.FreeOnly = true
		}
		choice := &Choice{selector: s, now: deps.Now, anchors: deps.Anchors, model: configured, nodes: map[string]*routingNode{}, providersReserved: map[string]bool{}, blocks: map[catalog.ModelCandidate]string{}, contexts: map[catalog.ModelCandidate]int{}}
		if !m.IsEnabled() {
			return choice, nil
		}
		for _, candidate := range m.Candidates {
			choice.blocks[candidate] = "source"
			weight := m.Weights[candidate.Identity()]
			if weight == 0 {
				weight = 1
			}
			if candidate.SourceID == catalog.GroupSource {
				childModel, ok := byID[candidate.Model]
				if !ok {
					return nil, errors.New("INVALID_MODEL_CATALOG")
				}
				configuredChild := childModel
				if m.FreeOnly && !m.AllowPlan {
					childModel.AllowPlan = false
				}
				child, err := build(childModel, depth+1, m.FreeOnly)
				if err != nil {
					return nil, err
				}
				child.model = configuredChild
				if len(child.targets) == 0 {
					continue
				}
				id := "group/" + childModel.ID
				target := routeTarget{ID: id, Member: candidate.Identity(), Kind: "group", Weight: weight, Channel: *s.channel(id, now)}
				childMemory := s.memory(child.model, deps.Anchors)
				ranked := rankRouteTargets(child.model.Strategy, child.targets, now, childMemory)
				if len(ranked) > 0 {
					target.Price = ranked[0].Price
					target.Quota = ranked[0].Quota
					if !availableTarget(ranked[0], now) {
						target.Channel.RestUntil = ranked[0].Channel.RestUntil
						target.Channel.ExhaustedUntil = ranked[0].Channel.ExhaustedUntil
					}
				}
				choice.targets = append(choice.targets, target)
				choice.nodes[id] = &routingNode{target: target, child: child}
				delete(choice.blocks, candidate)
				continue
			}
			fact, ok := facts[candidate.SourceID]
			if !ok {
				continue
			}
			var pluginModel *modelplugins.Model
			accounts := []modelplugins.Account{{Key: "", Type: "api"}}
			if fact.source.PluginSourceID != "" {
				if !PluginSignedIn(fact.plugin) {
					continue
				}
				for _, value := range fact.plugin.Models {
					if value.ID == candidate.Model {
						copy := value
						pluginModel = &copy
						break
					}
				}
				if pluginModel == nil {
					continue
				}
				accounts = fact.plugin.Accounts
				if len(accounts) == 0 {
					accounts = []modelplugins.Account{{Key: fact.plugin.ID}}
				}
				if len(accounts) > MaxSourceAccounts {
					return nil, errors.New("MODEL_ROUTE_TOO_LARGE")
				}
			}
			if requiredProtocol != "" {
				effective := fact.source.Protocol
				if pluginModel != nil {
					effective = modelplugins.ModelProtocol(*pluginModel, fact.plugin)
				}
				if effective != requiredProtocol {
					continue
				}
			}
			advertised := AccountPricingModel(pluginModel, len(accounts))
			if fact.source.PluginSourceID == "" {
				for _, detail := range fact.directory.Details {
					if detail.ID == candidate.Model {
						advertised = &modelplugins.Model{Tools: detail.Tools != nil && *detail.Tools, Context: detail.Context}
						break
					}
				}
			}
			if advertised != nil && advertised.Context > 0 {
				choice.contexts[candidate] = advertised.Context
			}
			if block := routeCapabilityBlock(m, advertised); block != "" {
				if fact.directory.Problem != "" {
					block = fact.directory.Problem
				}
				choice.blocks[candidate] = block
				continue
			}
			start := len(choice.targets)
			for _, account := range accounts {
				if len(account.Models) > 0 && !slices.Contains(account.Models, candidate.Model) {
					continue
				}
				quota := routingQuota{}
				if fact.valid[account.Key] {
					quota = quotaForModel(fact.quotas[account.Key], candidate.Model, now)
				}
				if !routeAllowed(m, candidate, advertised, quota, config.Pricing) {
					choice.blocks[candidate] = "pricing"
					continue
				}
				count++
				if count > 256 {
					return nil, errors.New("MODEL_ROUTE_TOO_LARGE")
				}
				channelID := candidate.Identity() + "/" + account.Key
				channel := *s.channel(channelID, now)
				if now.Sub(channel.RecentAt) > time.Hour {
					channel.Input, channel.Output = 0, 0
				}
				kind := "account"
				if account.Type == "api" || account.Type == "api_key" || fact.source.PluginSourceID == "" {
					kind = "key"
				}
				target := routeTarget{ID: channelID, Member: candidate.Identity(), Kind: kind, Weight: weight, Quota: quota, Channel: channel}
				price, known := config.Pricing.RoutePriceAt(candidate.SourceID, candidate.Model, now)
				if !known && pluginModel != nil && pluginModel.Cost != nil && config.Currency == "USD" {
					price = accounting.ModelPricing{pluginModel.Cost.Input, pluginModel.Cost.Output, pluginModel.Cost.CacheRead}
					factor := accounting.SourcePriceMultiplier(config.Pricing.Sources[candidate.SourceID], candidate.Model, now)
					price.InputPerMillion *= factor
					price.OutputPerMillion *= factor
					known = true
				}
				known = known && accounting.ValidAmount(price.InputPerMillion) && accounting.ValidAmount(price.OutputPerMillion) && accounting.ValidAmount(price.CacheReadPerMillion)
				if known {
					inputShare := .5
					if total := channel.Input + channel.Output; total > 0 {
						inputShare = float64(channel.Input) / float64(total)
					}
					value := price.InputPerMillion*inputShare + price.OutputPerMillion*(1-inputShare)
					target.Price = &value
				}
				choice.targets = append(choice.targets, target)
				choice.nodes[target.ID] = &routingNode{target: target, leaf: &Leaf{Candidate: candidate, Account: account.Key, ChannelID: channelID, Free: m.FreeOnly, PricingRevision: priceRevision, ProviderStrategy: config.Pricing.Sources[candidate.SourceID].AccountStrategy}}
			}
			if len(choice.targets) > start {
				delete(choice.blocks, candidate)
				if inspect && fact.source.PluginSourceID == "" {
					switch {
					case fact.directory.Problem != "":
						choice.blocks[candidate] = fact.directory.Problem
					case !fact.directory.ObservedAt.IsZero() && advertised == nil:
						choice.blocks[candidate] = "notListed"
					}
				}
			}
			if m.Strategy == "weight" && len(choice.targets) > start {
				provider := ProviderModel(candidate, config.Pricing.Sources[candidate.SourceID].AccountStrategy)
				providerMemory := s.memory(provider, deps.Anchors)
				ordered := rankRouteTargets(provider.Strategy, choice.targets[start:], now, providerMemory)
				choice.targets = append(choice.targets[:start], ordered...)
			}
		}
		return choice, nil
	}
	return build(model, 0, model.FreeOnly)
}
func (c *Choice) nextLocked() (Leaf, bool, error) {
	now := c.now()
	memory := c.selector.memory(c.model, c.anchors)
	if !c.initialized {
		c.ordered = rankRouteTargets(c.model.Strategy, c.targets, now, memory)
		c.initialized = true
	}
	for c.cursor < len(c.ordered) {
		target := c.ordered[c.cursor]
		node := c.nodes[target.ID]
		target.Channel = *c.selector.channel(target.ID, now)
		if !availableTarget(target, now) {
			reason := "cooldown"
			if target.Channel.ExhaustedUntil.After(now) || target.Quota.Remaining != nil && *target.Quota.Remaining <= 0 {
				reason = "quota"
			}
			if c.skips == nil {
				c.skips = map[string]int{}
			}
			c.skips[reason]++
			c.cursor++
			continue
		}
		if node.child != nil {
			leaf, ok, err := node.child.nextLocked()
			if err != nil {
				return Leaf{}, false, err
			}
			if !ok {
				c.cursor++
				continue
			}
			if err = c.selector.reserve(c.model, c.targets, target, memory, !c.reserved, c.anchors, now); err != nil {
				return Leaf{}, false, err
			}
			c.reserved = true
			leaf.Ancestors = append(leaf.Ancestors, target.ID)
			return leaf, true, nil
		}
		c.cursor++
		targets := append([]routeTarget(nil), c.targets...)
		for i := range targets {
			targets[i].Channel = *c.selector.channel(targets[i].ID, now)
		}
		if c.model.Strategy == "weight" {
			provider := ProviderModel(node.leaf.Candidate, node.leaf.ProviderStrategy)
			providerMemory := c.selector.memory(provider, c.anchors)
			own := []routeTarget{}
			for _, entry := range targets {
				if entry.Member == target.Member {
					own = append(own, entry)
				}
			}
			if err := c.selector.reserve(provider, own, target, providerMemory, !c.providersReserved[target.Member], c.anchors, now); err != nil {
				return Leaf{}, false, err
			}
			c.providersReserved[target.Member] = true
		}
		if err := c.selector.reserve(c.model, targets, target, memory, !c.reserved, c.anchors, now); err != nil {
			return Leaf{}, false, err
		}
		c.reserved = true
		return *node.leaf, true, nil
	}
	return Leaf{}, false, nil
}
func (c *Choice) unavailableReasons() map[string]int {
	result := map[string]int{}
	for _, reason := range c.blocks {
		result[reason]++
	}
	for reason, count := range c.skips {
		result[reason] += count
	}
	for _, node := range c.nodes {
		if node.child != nil && node.child.initialized {
			for reason, count := range node.child.unavailableReasons() {
				result[reason] += count
			}
		}
	}
	return result
}

func (c *Choice) UnavailableReasons() map[string]int {
	c.selector.mu.Lock()
	defer c.selector.mu.Unlock()
	return c.unavailableReasons()
}

func (c *Choice) Next() (Leaf, bool, error) {
	c.selector.mu.Lock()
	defer c.selector.mu.Unlock()
	return c.nextLocked()
}

func (c *Choice) NextAvailableAt() time.Time {
	c.selector.mu.Lock()
	defer c.selector.mu.Unlock()
	now := c.now()
	at := c.readyAtLocked(now)
	if !at.After(now) {
		return time.Time{}
	}
	return at
}

func (c *Choice) readyAtLocked(now time.Time) time.Time {
	var earliest time.Time
	for _, target := range c.targets {
		channel := c.selector.channel(target.ID, now)
		if channel.RestUntil.After(now) && channel.RestStatus != http.StatusTooManyRequests && channel.RestStatus != http.StatusPaymentRequired {
			continue
		}
		at := now
		for _, blockedUntil := range []time.Time{channel.RestUntil, channel.ExhaustedUntil} {
			if blockedUntil.After(at) {
				at = blockedUntil
			}
		}
		if target.Quota.Remaining != nil && *target.Quota.Remaining <= 0 {
			if !target.Quota.RetryAt.After(now) {
				continue
			}
			if target.Quota.RetryAt.After(at) {
				at = target.Quota.RetryAt
			}
		}
		if child := c.nodes[target.ID].child; child != nil {
			childAt := child.readyAtLocked(now)
			if childAt.IsZero() {
				continue
			}
			if childAt.After(at) {
				at = childAt
			}
		}
		if earliest.IsZero() || at.Before(earliest) {
			earliest = at
		}
	}
	return earliest
}

func (s *Selector) Rest(leaf Leaf, model catalog.CatalogModel, status int, retry time.Duration, now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	channel := s.channel(leaf.ChannelID, now)
	duration := time.Duration(model.Cooldown()) * time.Second
	if retry > duration {
		duration = retry
	}
	channel.RestUntil = now.Add(duration)
	channel.RestStatus = status
	if status == 402 {
		channel.ExhaustedUntil = channel.RestUntil
	}
}
func AccountLabel(account string) string {
	if len(account) > 200 {
		return ""
	}
	return strings.TrimSpace(account)
}
