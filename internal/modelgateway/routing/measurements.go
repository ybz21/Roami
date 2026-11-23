package routing

import (
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/protocol"
)

func (s *Selector) Observe(leaf Leaf, usage *protocol.Usage, successful bool, first, speed *float64, now func() time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, channelID := range append([]string{leaf.ChannelID}, leaf.Ancestors...) {
		channel := s.channel(channelID, now())
		if usage != nil {
			if time.Since(channel.RecentAt) > time.Hour {
				channel.Input, channel.Output = 0, 0
			}
			channel.Input += usage.Input
			channel.Output += usage.Output
			channel.RecentAt = time.Now()
		}
		if successful && first != nil && speed != nil {
			if channel.Measured.IsZero() {
				channel.FirstToken, channel.Speed = *first, *speed
			} else {
				channel.FirstToken = .3*channel.FirstToken + .7**first
				channel.Speed = .3*channel.Speed + .7**speed
			}
			channel.Measured = now()
		}
	}
}
