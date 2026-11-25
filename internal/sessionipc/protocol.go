package sessionipc

import (
	"encoding/json"
	"errors"

	"github.com/ybz21/Roami/internal/sessionbackend"
)

type rpcRequest struct {
	Method  string          `json:"method"`
	Payload json.RawMessage `json:"payload,omitempty"`
}

type rpcResponse struct {
	OK      bool            `json:"ok"`
	Code    string          `json:"code,omitempty"`
	Error   string          `json:"error,omitempty"`
	Payload json.RawMessage `json:"payload,omitempty"`
}

type healthReply struct {
	HostID      string                       `json:"hostId"`
	Protocol    int                          `json:"protocol"`
	ActivePanes int                          `json:"activePanes"`
	Draining    bool                         `json:"draining"`
	Caps        sessionbackend.CapabilitySet `json:"capabilities"`
}

type sessionIDReq struct {
	SessionID string `json:"sessionId"`
}

type renameReq struct {
	SessionID string `json:"sessionId"`
	Label     string `json:"label"`
}

type attachReq struct {
	Target sessionbackend.Target     `json:"target"`
	Opts   sessionbackend.AttachOpts `json:"opts"`
}

type claimReq struct {
	Target   sessionbackend.Target `json:"target"`
	ClientID string                `json:"clientId"`
}

type releaseReq struct {
	Target     sessionbackend.Target `json:"target"`
	ClientID   string                `json:"clientId"`
	ControlGen uint64                `json:"controlGen"`
}

type inputReq struct {
	Target     sessionbackend.Target `json:"target"`
	ControlGen uint64                `json:"controlGen"`
	Data       []byte                `json:"data"`
}

type submitReq struct {
	Target sessionbackend.Target    `json:"target"`
	Req    sessionbackend.SubmitReq `json:"req"`
}

type resizeReq struct {
	Target     sessionbackend.Target `json:"target"`
	ControlGen uint64                `json:"controlGen"`
	Cols       uint16                `json:"cols"`
	Rows       uint16                `json:"rows"`
}

type moveCursorReq struct {
	Target     sessionbackend.Target `json:"target"`
	ControlGen uint64                `json:"controlGen"`
	Col        int                   `json:"col"`
	Row        int                   `json:"row"`
}

type captureReq struct {
	Target sessionbackend.Target      `json:"target"`
	Opts   sessionbackend.CaptureOpts `json:"opts"`
}

type newWindowReq struct {
	SessionID string                    `json:"sessionId"`
	Spec      sessionbackend.WindowSpec `json:"spec"`
}

type windowIDReq struct {
	SessionID string `json:"sessionId"`
	WindowID  string `json:"windowId"`
}

type splitPaneReq struct {
	SessionID string                   `json:"sessionId"`
	PaneID    string                   `json:"paneId"`
	Spec      sessionbackend.SplitSpec `json:"spec"`
}

type splitPaneReply struct {
	Window sessionbackend.Window `json:"window"`
	PaneID string                `json:"paneId"`
}

type resizeSplitReq struct {
	SessionID       string  `json:"sessionId"`
	WindowID        string  `json:"windowId"`
	NodeID          string  `json:"nodeId"`
	Ratio           float64 `json:"ratio"`
	ExpectedVersion int64   `json:"expectedVersion"`
}

type focusPaneReq struct {
	SessionID string `json:"sessionId"`
	WindowID  string `json:"windowId"`
	PaneID    string `json:"paneId"`
}

type closePaneReq struct {
	SessionID string `json:"sessionId"`
	PaneID    string `json:"paneId"`
}

func errorCode(err error) string {
	switch {
	case errors.Is(err, sessionbackend.ErrSessionNotFound):
		return "SESSION_NOT_FOUND"
	case errors.Is(err, sessionbackend.ErrWindowNotFound):
		return "WINDOW_NOT_FOUND"
	case errors.Is(err, sessionbackend.ErrPaneNotFound):
		return "PANE_NOT_FOUND"
	case errors.Is(err, sessionbackend.ErrUnsupported):
		return "UNSUPPORTED"
	case errors.Is(err, sessionbackend.ErrStaleGeneration):
		return "STALE_GENERATION"
	case errors.Is(err, sessionbackend.ErrStaleControl):
		return "STALE_CONTROL_GENERATION"
	case errors.Is(err, sessionbackend.ErrLayoutConflict):
		return "LAYOUT_VERSION_CONFLICT"
	case errors.Is(err, sessionbackend.ErrPaneTooSmall):
		return "PANE_TOO_SMALL"
	case errors.Is(err, sessionbackend.ErrDrainingCap):
		return "DRAINING_GENERATION_LIMIT"
	default:
		return "INTERNAL_ERROR"
	}
}

func decodeError(code, msg string) error {
	switch code {
	case "SESSION_NOT_FOUND":
		return sessionbackend.ErrSessionNotFound
	case "WINDOW_NOT_FOUND":
		return sessionbackend.ErrWindowNotFound
	case "PANE_NOT_FOUND":
		return sessionbackend.ErrPaneNotFound
	case "UNSUPPORTED":
		return sessionbackend.ErrUnsupported
	case "STALE_GENERATION":
		return sessionbackend.ErrStaleGeneration
	case "STALE_CONTROL_GENERATION":
		return sessionbackend.ErrStaleControl
	case "LAYOUT_VERSION_CONFLICT":
		return sessionbackend.ErrLayoutConflict
	case "PANE_TOO_SMALL":
		return sessionbackend.ErrPaneTooSmall
	case "DRAINING_GENERATION_LIMIT":
		return sessionbackend.ErrDrainingCap
	default:
		if msg == "" {
			return errors.New("sessionipc: remote error")
		}
		return errors.New(msg)
	}
}
