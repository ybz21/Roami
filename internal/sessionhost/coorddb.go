package sessionhost

import "github.com/ybz21/Roami/internal/sessioncoord"

// Re-export sessioncoord types/constants for callers already importing sessionhost.
type (
	CoordDB         = sessioncoord.DB
	HostRecord      = sessioncoord.HostRecord
	HostPointer     = sessioncoord.HostPointer
	OperationRecord = sessioncoord.OperationRecord
)

const (
	HostStateReady          = sessioncoord.HostStateReady
	HostStateActive         = sessioncoord.HostStateActive
	HostStateDraining       = sessioncoord.HostStateDraining
	HostStateRetiring       = sessioncoord.HostStateRetiring
	HostStateRetired        = sessioncoord.HostStateRetired
	OpStateAccepted         = sessioncoord.OpStateAccepted
	OpStateStarting         = sessioncoord.OpStateStarting
	OpStateSucceeded        = sessioncoord.OpStateSucceeded
	OpStateFailed           = sessioncoord.OpStateFailed
	DefaultMaxDrainingHosts = sessioncoord.DefaultMaxDrainingHosts
)

var (
	ErrOperationConflict = sessioncoord.ErrOperationConflict
	ErrHostNotReady      = sessioncoord.ErrHostNotReady
	ErrHostStillActive   = sessioncoord.ErrHostStillActive
	OpenCoordDB          = sessioncoord.Open
)
