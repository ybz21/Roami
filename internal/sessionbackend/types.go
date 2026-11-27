// Package sessionbackend defines the business-level session, pane, and window layout contracts
// shared by the tmux compatibility adapter and the native roami-sessiond host.
package sessionbackend

import (
	"context"
	"errors"
	"time"
)

var (
	ErrSessionNotFound  = errors.New("sessionbackend: session not found")
	ErrWindowNotFound   = errors.New("sessionbackend: window not found")
	ErrPaneNotFound     = errors.New("sessionbackend: pane not found")
	ErrUnsupported      = errors.New("sessionbackend: capability unsupported")
	ErrStaleGeneration  = errors.New("STALE_GENERATION")
	ErrStaleControl     = errors.New("STALE_CONTROL_GENERATION")
	ErrLayoutConflict   = errors.New("LAYOUT_VERSION_CONFLICT")
	ErrPaneTooSmall     = errors.New("PANE_TOO_SMALL")
	ErrDrainingCap      = errors.New("DRAINING_GENERATION_LIMIT")
	ErrSessionUncertain = errors.New("SESSION_STATE_UNCERTAIN")
)

type BackendKind string

const (
	BackendTmux   BackendKind = "tmux"
	BackendNative BackendKind = "native"
)

type LifecycleStatus string

const (
	StatusAlive   LifecycleStatus = "alive"
	StatusExited  LifecycleStatus = "exited"
	StatusUnknown LifecycleStatus = "unknown"
)

// Target addresses a session, optional window, and optional pane.
// Omitting WindowID/PaneID targets the active window/pane.
type Target struct {
	SessionID string `json:"sessionId"`
	WindowID  string `json:"windowId,omitempty"`
	PaneID    string `json:"paneId,omitempty"`
}

// CreateSpec defines typed session creation parameters shared across backends.
type CreateSpec struct {
	SessionID          string   `json:"sessionId,omitempty"`
	OperationID        string   `json:"operationId,omitempty"`
	Label              string   `json:"label,omitempty"`
	Dir                string   `json:"dir,omitempty"`
	Exe                string   `json:"exe,omitempty"`
	Args               []string `json:"args,omitempty"`
	Env                []string `json:"env,omitempty"`
	Cols               uint16   `json:"cols,omitempty"`
	Rows               uint16   `json:"rows,omitempty"`
	LoginShell         bool     `json:"loginShell,omitempty"`
	ExpectedGeneration int64    `json:"expectedGeneration,omitempty"`
}

// SessionRef identifies a newly created or resolved session.
type SessionRef struct {
	SessionID      string      `json:"sessionId"`
	Label          string      `json:"label,omitempty"`
	Backend        BackendKind `json:"backend"`
	HostInstanceID string      `json:"hostInstanceId,omitempty"`
	WindowID       string      `json:"windowId,omitempty"`
	PaneID         string      `json:"paneId,omitempty"`
	RunGeneration  int64       `json:"runGeneration,omitempty"`
	PID            int         `json:"pid,omitempty"`
	ProcessID      string      `json:"processIdentity,omitempty"`
	Reused         bool        `json:"reused,omitempty"`
}

// SessionState distinguishes confirmed liveness, confirmed exit, and uncertain observation.
type SessionState struct {
	SessionID      string          `json:"sessionId"`
	Label          string          `json:"label,omitempty"`
	Backend        BackendKind     `json:"backend"`
	HostInstanceID string          `json:"hostInstanceId,omitempty"`
	Status         LifecycleStatus `json:"status"`
	ExitCode       *int            `json:"exitCode,omitempty"`
	Signal         string          `json:"signal,omitempty"`
	Reason         string          `json:"reason,omitempty"`
	ActiveWindowID string          `json:"activeWindowId,omitempty"`
	ActivePaneID   string          `json:"activePaneId,omitempty"`
	Windows        []Window        `json:"windows,omitempty"`
	PID            int             `json:"pid,omitempty"`
	ProcessID      string          `json:"processIdentity,omitempty"`
	Cwd            string          `json:"cwd,omitempty"`
	CreatedAt      time.Time       `json:"createdAt,omitempty"`
	LastActivityAt time.Time       `json:"lastActivityAt,omitempty"`
	Attached       int             `json:"attached,omitempty"`
}

// SessionSummary is the lightweight listing projection returned by List.
type SessionSummary struct {
	ID             string          `json:"id"`
	Label          string          `json:"label,omitempty"`
	Backend        BackendKind     `json:"backend"`
	HostInstanceID string          `json:"hostInstanceId,omitempty"`
	Status         LifecycleStatus `json:"status"`
	Windows        int             `json:"windows"`
	CreatedAt      time.Time       `json:"createdAt"`
	LastActivityAt time.Time       `json:"lastActivityAt"`
	Attached       int             `json:"attached"`
	Dir            string          `json:"dir,omitempty"`
}

// TerminalMode captures authoritative VT state maintained by the host.
type TerminalMode struct {
	AltScreen      bool   `json:"altScreen"`
	MouseOn        bool   `json:"mouseOn"`
	MouseSGR       bool   `json:"mouseSgr"`
	DECCKM         bool   `json:"decckm"`
	BracketedPaste bool   `json:"bracketedPaste"`
	CursorX        int    `json:"cursorX"`
	CursorY        int    `json:"cursorY"`
	Cols           uint16 `json:"cols"`
	Rows           uint16 `json:"rows"`
}

// CaptureOpts configures screen capture behavior.
type CaptureOpts struct {
	Lines          int  `json:"lines,omitempty"`
	IncludeHistory bool `json:"includeHistory,omitempty"`
	IncludeStyles  bool `json:"includeStyles,omitempty"`
}

// CaptureResult holds plain text screen content and optional styling metadata.
type CaptureResult struct {
	Text      string       `json:"text"`
	PaneGen   int64        `json:"paneGen"`
	Mode      TerminalMode `json:"mode"`
	Truncated bool         `json:"truncated,omitempty"`
}

// SubmitReq is a managed, idempotent prompt/command delivery request.
type SubmitReq struct {
	RequestID      string `json:"requestId"`
	Payload        string `json:"payload"`
	SubmitEnter    bool   `json:"submitEnter"`
	BracketedPaste bool   `json:"bracketedPaste"`
}

// SubmitReceipt records the durable outcome of a managed submission.
type SubmitReceipt struct {
	RequestID string    `json:"requestId"`
	Accepted  bool      `json:"accepted"`
	Duplicate bool      `json:"duplicate,omitempty"`
	At        time.Time `json:"at"`
}

// CapabilitySet advertises backend features so UI/CLI avoid OS or backend guessing.
type CapabilitySet struct {
	Windows        bool `json:"windows"`
	Splits         bool `json:"splits"`
	MoveCursor     bool `json:"moveCursor"`
	ManagedSubmit  bool `json:"managedSubmit"`
	MemoryLimit    bool `json:"memoryLimit"`
	Pause          bool `json:"pause"`
	ProcessInspect bool `json:"processInspect"`
}

// AttachOpts configures a detachable pane subscription.
type AttachOpts struct {
	LastSeq  uint64 `json:"lastSeq,omitempty"`
	ReadOnly bool   `json:"readOnly,omitempty"`
	ClientID string `json:"clientId,omitempty"`
}

type StreamEventKind string

const (
	EventSnapshot      StreamEventKind = "snapshot"
	EventOutput        StreamEventKind = "output"
	EventMode          StreamEventKind = "mode"
	EventResized       StreamEventKind = "resized"
	EventLayoutChanged StreamEventKind = "layout_changed"
	EventControl       StreamEventKind = "control"
	EventExited        StreamEventKind = "exited"
	EventResyncNeeded  StreamEventKind = "resync_needed"
)

// StreamEvent is one ordered frame on a pane's event stream.
type StreamEvent struct {
	Seq        uint64          `json:"seq"`
	PaneID     string          `json:"paneId"`
	PaneGen    int64           `json:"paneGen"`
	Kind       StreamEventKind `json:"kind"`
	Data       []byte          `json:"data,omitempty"`
	Mode       *TerminalMode   `json:"mode,omitempty"`
	Window     *Window         `json:"window,omitempty"`
	ControlGen uint64          `json:"controlGen,omitempty"`
	Controller string          `json:"controller,omitempty"`
	ExitCode   *int            `json:"exitCode,omitempty"`
	Signal     string          `json:"signal,omitempty"`
	Drained    bool            `json:"drained,omitempty"`
}

// PaneStream is a detachable subscription to a pane's ordered event stream.
// Closing the stream only unsubscribes; it never terminates the running process.
type PaneStream interface {
	Events() <-chan StreamEvent
	Close() error
}

// ControlLease records who holds active input/resize control of a pane.
type ControlLease struct {
	PaneID     string `json:"paneId"`
	Controller string `json:"controller"`
	ControlGen uint64 `json:"controlGen"`
}

// SessionBackend is Layer 1: unified business interface implemented by tmux and native hosts.
type SessionBackend interface {
	Kind() BackendKind
	Capabilities() CapabilitySet

	Create(ctx context.Context, spec CreateSpec) (SessionRef, error)
	Observe(ctx context.Context, sessionID string) (SessionState, error)
	List(ctx context.Context) ([]SessionSummary, error)
	Close(ctx context.Context, sessionID string) error
	Rename(ctx context.Context, sessionID, label string) error

	Attach(ctx context.Context, target Target, opts AttachOpts) (PaneStream, error)
	ClaimControl(ctx context.Context, target Target, clientID string) (ControlLease, error)
	ReleaseControl(ctx context.Context, target Target, clientID string, controlGen uint64) error
	WriteInput(ctx context.Context, target Target, controlGen uint64, data []byte) error
	Submit(ctx context.Context, target Target, req SubmitReq) (SubmitReceipt, error)
	Resize(ctx context.Context, target Target, controlGen uint64, cols, rows uint16) error
	MoveCursor(ctx context.Context, target Target, controlGen uint64, col, row int) error
	Capture(ctx context.Context, target Target, opts CaptureOpts) (CaptureResult, error)
}

// WindowSpec configures a new window within an existing session.
type WindowSpec struct {
	Name       string   `json:"name,omitempty"`
	Dir        string   `json:"dir,omitempty"`
	Exe        string   `json:"exe,omitempty"`
	Args       []string `json:"args,omitempty"`
	Env        []string `json:"env,omitempty"`
	Cols       uint16   `json:"cols,omitempty"`
	Rows       uint16   `json:"rows,omitempty"`
	LoginShell bool     `json:"loginShell,omitempty"`
}

// SplitSpec configures splitting an existing pane horizontally or vertically.
type SplitSpec struct {
	Dir        SplitDir `json:"dir"`
	Ratio      float64  `json:"ratio,omitempty"`
	Cwd        string   `json:"cwd,omitempty"`
	Exe        string   `json:"exe,omitempty"`
	Args       []string `json:"args,omitempty"`
	Env        []string `json:"env,omitempty"`
	Cols       uint16   `json:"cols,omitempty"`
	Rows       uint16   `json:"rows,omitempty"`
	LoginShell bool     `json:"loginShell,omitempty"`
}

// LayoutBackend is the reserved interface for multi-window and horizontal/vertical split operations.
type LayoutBackend interface {
	NewWindow(ctx context.Context, sessionID string, spec WindowSpec) (Window, error)
	ListWindows(ctx context.Context, sessionID string) ([]Window, error)
	SelectWindow(ctx context.Context, sessionID, windowID string) error
	CloseWindow(ctx context.Context, sessionID, windowID string) error

	SplitPane(ctx context.Context, sessionID, paneID string, spec SplitSpec) (Window, string, error)
	ResizeSplit(ctx context.Context, sessionID, windowID, nodeID string, ratio float64, expectedVersion int64) (Window, error)
	FocusPane(ctx context.Context, sessionID, windowID, paneID string) (Window, error)
	ClosePane(ctx context.Context, sessionID, paneID string) (*Window, error)
}
