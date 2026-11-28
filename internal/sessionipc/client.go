package sessionipc

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"sync"
	"time"

	"github.com/hashicorp/yamux"
	"github.com/ybz21/Roami/internal/sessionbackend"
)

// Client connects to a roami-term instance over yamux and implements both
// SessionBackend and LayoutBackend transparently.
type Client struct {
	desc EndpointDescriptor

	mu   sync.Mutex
	mux  *yamux.Session
	caps sessionbackend.CapabilitySet
}

var (
	_ sessionbackend.SessionBackend = (*Client)(nil)
	_ sessionbackend.LayoutBackend  = (*Client)(nil)
)

func Dial(ctx context.Context, desc EndpointDescriptor) (*Client, error) {
	c := &Client{desc: desc}
	if _, err := c.ensureMux(ctx); err != nil {
		return nil, err
	}
	var h healthReply
	if err := c.call(ctx, "health", nil, &h); err != nil {
		_ = c.CloseConn()
		return nil, err
	}
	c.caps = h.Caps
	return c, nil
}

func (c *Client) ensureMux(ctx context.Context) (*yamux.Session, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.mux != nil && !c.mux.IsClosed() {
		return c.mux, nil
	}
	var d net.Dialer
	d.Timeout = 5 * time.Second
	conn, err := d.DialContext(ctx, c.desc.Network, c.desc.Address)
	if err != nil {
		return nil, err
	}
	if _, err := clientHandshake(conn, c.desc.Token); err != nil {
		_ = conn.Close()
		return nil, err
	}
	cfg := yamux.DefaultConfig()
	cfg.LogOutput = io.Discard
	mux, err := yamux.Client(conn, cfg)
	if err != nil {
		_ = conn.Close()
		return nil, err
	}
	c.mux = mux
	return mux, nil
}

func (c *Client) CloseConn() error {
	c.mu.Lock()
	mux := c.mux
	c.mux = nil
	c.mu.Unlock()
	if mux != nil {
		return mux.Close()
	}
	return nil
}

func (c *Client) call(ctx context.Context, method string, in any, out any) error {
	mux, err := c.ensureMux(ctx)
	if err != nil {
		return err
	}
	stream, err := mux.Open()
	if err != nil {
		return err
	}
	defer stream.Close()
	if dl, ok := ctx.Deadline(); ok {
		_ = stream.SetDeadline(dl)
	}
	var payload json.RawMessage
	if in != nil {
		payload, err = json.Marshal(in)
		if err != nil {
			return err
		}
	}
	if err := writeJSONFrame(stream, rpcRequest{Method: method, Payload: payload}); err != nil {
		return err
	}
	var resp rpcResponse
	if err := readJSONFrame(stream, &resp); err != nil {
		return err
	}
	if !resp.OK {
		return decodeError(resp.Code, resp.Error)
	}
	if out != nil && len(resp.Payload) > 0 && string(resp.Payload) != "null" {
		return json.Unmarshal(resp.Payload, out)
	}
	return nil
}

func (c *Client) Kind() sessionbackend.BackendKind           { return sessionbackend.BackendNative }
func (c *Client) Capabilities() sessionbackend.CapabilitySet { return c.caps }

func (c *Client) Health(ctx context.Context) (healthReply, error) {
	var h healthReply
	err := c.call(ctx, "health", nil, &h)
	return h, err
}

func (c *Client) Drain(ctx context.Context) (healthReply, error) {
	var h healthReply
	err := c.call(ctx, "drain", nil, &h)
	return h, err
}

func (c *Client) Create(ctx context.Context, spec sessionbackend.CreateSpec) (sessionbackend.SessionRef, error) {
	var ref sessionbackend.SessionRef
	err := c.call(ctx, "create", spec, &ref)
	return ref, err
}

func (c *Client) Observe(ctx context.Context, sessionID string) (sessionbackend.SessionState, error) {
	var st sessionbackend.SessionState
	err := c.call(ctx, "observe", sessionIDReq{SessionID: sessionID}, &st)
	if err != nil && st.Status == "" {
		st = sessionbackend.SessionState{
			SessionID:      sessionID,
			Backend:        sessionbackend.BackendNative,
			HostInstanceID: c.desc.HostID,
			Status:         sessionbackend.StatusUnknown,
			Reason:         err.Error(),
		}
	}
	return st, err
}

func (c *Client) List(ctx context.Context) ([]sessionbackend.SessionSummary, error) {
	var list []sessionbackend.SessionSummary
	err := c.call(ctx, "list", nil, &list)
	return list, err
}

func (c *Client) Close(ctx context.Context, sessionID string) error {
	return c.call(ctx, "close", sessionIDReq{SessionID: sessionID}, nil)
}

func (c *Client) Rename(ctx context.Context, sessionID, label string) error {
	return c.call(ctx, "rename", renameReq{SessionID: sessionID, Label: label}, nil)
}

func (c *Client) ClaimControl(ctx context.Context, target sessionbackend.Target, clientID string) (sessionbackend.ControlLease, error) {
	var lease sessionbackend.ControlLease
	err := c.call(ctx, "claim", claimReq{Target: target, ClientID: clientID}, &lease)
	return lease, err
}

func (c *Client) ReleaseControl(ctx context.Context, target sessionbackend.Target, clientID string, controlGen uint64) error {
	return c.call(ctx, "release", releaseReq{Target: target, ClientID: clientID, ControlGen: controlGen}, nil)
}

func (c *Client) WriteInput(ctx context.Context, target sessionbackend.Target, controlGen uint64, data []byte) error {
	return c.call(ctx, "input", inputReq{Target: target, ControlGen: controlGen, Data: data}, nil)
}

func (c *Client) Submit(ctx context.Context, target sessionbackend.Target, req sessionbackend.SubmitReq) (sessionbackend.SubmitReceipt, error) {
	var rec sessionbackend.SubmitReceipt
	err := c.call(ctx, "submit", submitReq{Target: target, Req: req}, &rec)
	return rec, err
}

func (c *Client) Resize(ctx context.Context, target sessionbackend.Target, controlGen uint64, cols, rows uint16) error {
	return c.call(ctx, "resize", resizeReq{Target: target, ControlGen: controlGen, Cols: cols, Rows: rows}, nil)
}

func (c *Client) MoveCursor(ctx context.Context, target sessionbackend.Target, controlGen uint64, col, row int) error {
	return c.call(ctx, "move_cursor", moveCursorReq{Target: target, ControlGen: controlGen, Col: col, Row: row}, nil)
}

func (c *Client) Capture(ctx context.Context, target sessionbackend.Target, opts sessionbackend.CaptureOpts) (sessionbackend.CaptureResult, error) {
	var res sessionbackend.CaptureResult
	err := c.call(ctx, "capture", captureReq{Target: target, Opts: opts}, &res)
	return res, err
}

type ipcPaneStream struct {
	stream net.Conn
	ch     chan sessionbackend.StreamEvent
	once   sync.Once
}

func (s *ipcPaneStream) Events() <-chan sessionbackend.StreamEvent { return s.ch }

func (s *ipcPaneStream) Close() error {
	var err error
	s.once.Do(func() {
		err = s.stream.Close()
	})
	return err
}

func (c *Client) Attach(ctx context.Context, target sessionbackend.Target, opts sessionbackend.AttachOpts) (sessionbackend.PaneStream, error) {
	mux, err := c.ensureMux(ctx)
	if err != nil {
		return nil, err
	}
	stream, err := mux.Open()
	if err != nil {
		return nil, err
	}
	payload, _ := json.Marshal(attachReq{Target: target, Opts: opts})
	if err := writeJSONFrame(stream, rpcRequest{Method: "attach", Payload: payload}); err != nil {
		_ = stream.Close()
		return nil, err
	}
	var resp rpcResponse
	if err := readJSONFrame(stream, &resp); err != nil {
		_ = stream.Close()
		return nil, err
	}
	if !resp.OK {
		_ = stream.Close()
		return nil, decodeError(resp.Code, resp.Error)
	}

	ps := &ipcPaneStream{
		stream: stream,
		ch:     make(chan sessionbackend.StreamEvent, 128),
	}
	go func() {
		defer close(ps.ch)
		defer stream.Close()
		for {
			var ev sessionbackend.StreamEvent
			if err := readJSONFrame(stream, &ev); err != nil {
				return
			}
			select {
			case ps.ch <- ev:
			case <-ctx.Done():
				return
			}
		}
	}()
	return ps, nil
}

// ── LayoutBackend over IPC ──────────────────────────────────────────────────

func (c *Client) NewWindow(ctx context.Context, sessionID string, spec sessionbackend.WindowSpec) (sessionbackend.Window, error) {
	var w sessionbackend.Window
	err := c.call(ctx, "new_window", newWindowReq{SessionID: sessionID, Spec: spec}, &w)
	return w, err
}

func (c *Client) ListWindows(ctx context.Context, sessionID string) ([]sessionbackend.Window, error) {
	var list []sessionbackend.Window
	err := c.call(ctx, "list_windows", sessionIDReq{SessionID: sessionID}, &list)
	return list, err
}

func (c *Client) SelectWindow(ctx context.Context, sessionID, windowID string) error {
	return c.call(ctx, "select_window", windowIDReq{SessionID: sessionID, WindowID: windowID}, nil)
}

func (c *Client) CloseWindow(ctx context.Context, sessionID, windowID string) error {
	return c.call(ctx, "close_window", windowIDReq{SessionID: sessionID, WindowID: windowID}, nil)
}

func (c *Client) SplitPane(ctx context.Context, sessionID, paneID string, spec sessionbackend.SplitSpec) (sessionbackend.Window, string, error) {
	var reply splitPaneReply
	err := c.call(ctx, "split_pane", splitPaneReq{SessionID: sessionID, PaneID: paneID, Spec: spec}, &reply)
	return reply.Window, reply.PaneID, err
}

func (c *Client) ResizeSplit(ctx context.Context, sessionID, windowID, nodeID string, ratio float64, expectedVersion int64) (sessionbackend.Window, error) {
	var w sessionbackend.Window
	err := c.call(ctx, "resize_split", resizeSplitReq{
		SessionID: sessionID, WindowID: windowID, NodeID: nodeID, Ratio: ratio, ExpectedVersion: expectedVersion,
	}, &w)
	return w, err
}

func (c *Client) FocusPane(ctx context.Context, sessionID, windowID, paneID string) (sessionbackend.Window, error) {
	var w sessionbackend.Window
	err := c.call(ctx, "focus_pane", focusPaneReq{SessionID: sessionID, WindowID: windowID, PaneID: paneID}, &w)
	return w, err
}

func (c *Client) ClosePane(ctx context.Context, sessionID, paneID string) (*sessionbackend.Window, error) {
	var w *sessionbackend.Window
	err := c.call(ctx, "close_pane", closePaneReq{SessionID: sessionID, PaneID: paneID}, &w)
	return w, err
}

func (c *Client) String() string {
	return fmt.Sprintf("sessionipc.Client(%s@%s)", c.desc.HostID, c.desc.Address)
}
