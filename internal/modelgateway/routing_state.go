package modelgateway

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"math"
	"sort"
	"sync"
	"time"
)

type routeChannel struct {
	RestUntil         time.Time
	ExhaustedUntil    time.Time
	Input, Output     int64
	RecentAt          time.Time
	FirstToken, Speed float64
	Measured          time.Time
	Touched           time.Time
}
type routeMemory struct {
	Fingerprint, Anchor string
	Turn                uint64
	Weights             map[string]int64
}
type routingState struct {
	mu       sync.Mutex
	models   map[string]*routeMemory
	channels map[string]*routeChannel
	quota    quotaCache
}
type routeTarget struct {
	ID, Member, Kind string
	Weight           int
	Quota            routingQuota
	Price            *float64
	Channel          routeChannel
}

func (s *routingState) channel(id string, now time.Time) *routeChannel {
	if s.channels == nil {
		s.channels = map[string]*routeChannel{}
	}
	if value := s.channels[id]; value != nil {
		value.Touched = now
		return value
	}
	if len(s.channels) >= 16384 {
		var oldest string
		var stamp time.Time
		for key, value := range s.channels {
			if oldest == "" || value.Touched.Before(stamp) {
				oldest, stamp = key, value.Touched
			}
		}
		delete(s.channels, oldest)
	}
	value := &routeChannel{Touched: now}
	s.channels[id] = value
	return value
}
func routingFingerprint(model CatalogModel) string {
	model.Name = ""
	model.Enabled = nil
	raw, _ := json.Marshal(model)
	hash := sha256.Sum256(raw)
	return hex.EncodeToString(hash[:])
}
func (s *routingState) memory(model CatalogModel, ledger *Ledger) *routeMemory {
	if s.models == nil {
		s.models = map[string]*routeMemory{}
	}
	fingerprint := routingFingerprint(model)
	if memory := s.models[model.ID]; memory != nil && memory.Fingerprint == fingerprint {
		return memory
	}
	if len(s.models) >= 1000 {
		s.models = map[string]*routeMemory{}
	}
	memory := &routeMemory{Fingerprint: fingerprint, Weights: map[string]int64{}}
	var anchor, stored string
	if ledger != nil {
		_ = ledger.db.QueryRow(`SELECT fingerprint,anchor FROM gateway_route_anchors WHERE model_id=?`, model.ID).Scan(&stored, &anchor)
		if stored == fingerprint {
			memory.Anchor = anchor
		}
	}
	s.models[model.ID] = memory
	return memory
}
func firstExpiry(quota routingQuota) time.Time {
	var result time.Time
	for _, credit := range quota.Credits {
		if credit.Amount > 0 && (result.IsZero() || credit.At.Before(result)) {
			result = credit.At
		}
	}
	return result
}
func quotaUrgency(quota routingQuota, now time.Time) float64 {
	result := float64(0)
	if quota.Remaining != nil && quota.Reset.After(now) {
		result = *quota.Remaining / quota.Reset.Sub(now).Hours()
	}
	expiry := firstExpiry(quota)
	if expiry.After(now) && (quota.Reset.IsZero() || expiry.Before(quota.Reset)) {
		amount := float64(0)
		for _, credit := range quota.Credits {
			if credit.At.Equal(expiry) {
				amount += credit.Amount
			}
		}
		result = math.Max(result, amount/expiry.Sub(now).Hours())
	}
	return result
}
func availableTarget(target routeTarget, now time.Time) bool {
	return !target.Channel.RestUntil.After(now) && !target.Channel.ExhaustedUntil.After(now) && (target.Quota.Remaining == nil || *target.Quota.Remaining > 0)
}
func rankRouteTargets(strategy string, targets []routeTarget, now time.Time, memory *routeMemory) []routeTarget {
	result := append([]routeTarget(nil), targets...)
	original := map[string]int{}
	for index, target := range targets {
		original[target.ID] = index
	}
	compareTime := func(a, b time.Time) int {
		if a.IsZero() && b.IsZero() {
			return 0
		}
		if a.IsZero() {
			return 1
		}
		if b.IsZero() {
			return -1
		}
		if a.Before(b) {
			return -1
		}
		if a.After(b) {
			return 1
		}
		return 0
	}
	smart := func(a, b routeTarget) int {
		ar, br := a.Quota.Reset, b.Quota.Reset
		if ar.IsZero() {
			ar = firstExpiry(a.Quota)
		}
		if br.IsZero() {
			br = firstExpiry(b.Quota)
		}
		if cmp := compareTime(ar, br); cmp != 0 {
			return cmp
		}
		return compareTime(firstExpiry(a.Quota), firstExpiry(b.Quota))
	}
	less := func(a, b routeTarget) bool {
		switch strategy {
		case "smart":
			if cmp := smart(a, b); cmp != 0 {
				return cmp < 0
			}
		case "usage":
			if a.Quota.Remaining != nil && b.Quota.Remaining == nil {
				return true
			}
			if a.Quota.Remaining == nil && b.Quota.Remaining != nil {
				return false
			}
			if a.Quota.Remaining != nil && *a.Quota.Remaining != *b.Quota.Remaining {
				return *a.Quota.Remaining > *b.Quota.Remaining
			}
		case "pace":
			reserve := func(value routeTarget) bool {
				return value.Kind != "key" && value.Quota.Remaining != nil && value.Quota.Capacity != nil && *value.Quota.Capacity > 0 && *value.Quota.Remaining / *value.Quota.Capacity <= .1
			}
			if reserve(a) != reserve(b) {
				return !reserve(a)
			}
			if a.Kind == "key" && b.Kind == "key" {
				if a.Channel.Input+a.Channel.Output != b.Channel.Input+b.Channel.Output {
					return a.Channel.Input+a.Channel.Output < b.Channel.Input+b.Channel.Output
				}
			} else if a.Kind == "key" || b.Kind == "key" {
				return a.Kind != "key"
			} else if aa, bb := quotaUrgency(a.Quota, now), quotaUrgency(b.Quota, now); aa != bb {
				return aa > bb
			}
		case "cheap":
			if a.Price != nil && b.Price == nil {
				return true
			}
			if a.Price == nil && b.Price != nil {
				return false
			}
			if a.Price != nil && *a.Price != *b.Price {
				return *a.Price < *b.Price
			}
		}
		return original[a.ID] < original[b.ID]
	}
	if containsField([]string{"smart", "usage", "pace", "cheap"}, strategy) {
		sort.SliceStable(result, func(i, j int) bool { return less(result[i], result[j]) })
	}
	if strategy == "rotate" && len(result) > 0 {
		offset := int(memory.Turn % uint64(len(result)))
		result = append(result[offset:], result[:offset]...)
	}
	if strategy == "drain" && memory.Anchor != "" {
		for index, target := range result {
			if target.ID == memory.Anchor {
				result = append(result[index:], result[:index]...)
				break
			}
		}
	}
	if strategy == "weight" {
		groups := []string{}
		members := map[string][]routeTarget{}
		for _, target := range result {
			if !availableTarget(target, now) {
				continue
			}
			if len(members[target.Member]) == 0 {
				groups = append(groups, target.Member)
			}
			members[target.Member] = append(members[target.Member], target)
		}
		sort.SliceStable(groups, func(i, j int) bool {
			return memory.Weights[groups[i]]+int64(members[groups[i]][0].Weight) > memory.Weights[groups[j]]+int64(members[groups[j]][0].Weight)
		})
		result = nil
		for _, member := range groups {
			channels := members[member]

			result = append(result, channels...)
		}
		for _, target := range targets {
			if !availableTarget(target, now) {
				result = append(result, target)
			}
		}
	}
	if strategy == "fast" {
		score := func(value routeTarget) float64 {
			if value.Channel.Measured.IsZero() || value.Channel.Speed <= 0 {
				return math.Inf(1)
			}
			return value.Channel.FirstToken + 100000/value.Channel.Speed
		}
		ordered := []routeTarget{}
		for _, target := range result {
			index := len(ordered)
			for i, value := range ordered {
				if score(target) < score(value)*.9 {
					index = i
					break
				}
			}
			ordered = append(ordered, routeTarget{})
			copy(ordered[index+1:], ordered[index:])
			ordered[index] = target
		}
		result = ordered
		if memory.Turn%5 == 4 {
			stale := []routeTarget{}
			for _, target := range targets {
				if now.Sub(target.Channel.Measured) >= time.Hour && availableTarget(target, now) {
					stale = append(stale, target)
				}
			}
			if len(stale) > 0 {
				probe := stale[int(memory.Turn/5)%len(stale)]
				next := []routeTarget{probe}
				for _, target := range result {
					if target.ID != probe.ID {
						next = append(next, target)
					}
				}
				result = next
			}
		}
	}
	active, resting := []routeTarget{}, []routeTarget{}
	for _, target := range result {
		if availableTarget(target, now) {
			active = append(active, target)
		} else {
			resting = append(resting, target)
		}
	}
	return append(active, resting...)
}
func (s *routingState) reserve(model CatalogModel, targets []routeTarget, target routeTarget, memory *routeMemory, first bool, ledger *Ledger, now time.Time) error {
	if model.Strategy == "drain" {
		anchorAvailable := false
		for _, value := range targets {
			if value.ID == memory.Anchor {
				anchorAvailable = !value.Channel.ExhaustedUntil.After(now) && (value.Quota.Remaining == nil || *value.Quota.Remaining > 0)
			}
		}
		if memory.Anchor == "" || !anchorAvailable {
			if ledger != nil {
				err := ledger.db.Tx(func(tx *sql.Tx) error {
					_, err := tx.Exec(`INSERT INTO gateway_route_anchors(model_id,fingerprint,anchor) VALUES(?,?,?) ON CONFLICT(model_id) DO UPDATE SET fingerprint=excluded.fingerprint,anchor=excluded.anchor`, model.ID, memory.Fingerprint, target.ID)
					return err
				})
				if err != nil {
					return err
				}
			}
			memory.Anchor = target.ID
		}
	}
	if !first {
		return nil
	}
	memory.Turn++
	if model.Strategy == "rotate" {
		for index, value := range targets {
			if value.ID == target.ID {
				memory.Turn = uint64(index + 1)
				break
			}
		}
	}
	if model.Strategy == "weight" {
		members := map[string]int{}
		for _, value := range targets {
			if availableTarget(value, now) {
				members[value.Member] = value.Weight
			}
		}
		var total int64
		for member, weight := range members {
			memory.Weights[member] += int64(weight)
			total += int64(weight)
		}
		memory.Weights[target.Member] -= total
	}
	return nil
}
