package sessionipc

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"sync"

	"github.com/hashicorp/yamux"
	"github.com/ybz21/Roami/internal/sessionbackend"
)

// HostService is the minimal interface served by sessionipc.Server, keeping sessionipc
// completely decoupled from internal/sessionhost and internal/terminal.
type HostService interface {
	sessionbackend.SessionBackend
	HostID() string
	ActivePaneCount() int
	IsDraining() bool
	SetDraining(bool)
}

// Server exposes a HostService over an authenticated yamux-multiplexed local listener.
type Server struct {
	host       HostService
	ln         net.Listener
	network    string
	address    string
	token      string
	descriptor EndpointDescriptor

	mu     sync.Mutex
	closed bool
}

func NewServer(host HostService, instanceRoot string) (*Server, error) {
	token, err := GenerateToken()
	if err != nil {
		return nil, err
	}
	ln, network, address, err := ListenLocal(instanceRoot, host.HostID())
	if err != nil {
		return nil, err
	}
	desc := EndpointDescriptor{
		HostID:      host.HostID(),
		Network:     network,
		Address:     address,
		Token:       token,
		ProtocolMin: ProtocolVersion,
		ProtocolMax: ProtocolVersion,
		PID:         os.Getpid(),
	}
	return &Server{
		host:       host,
		ln:         ln,
		network:    network,
		address:    address,
		token:      token,
		descriptor: desc,
	}, nil
}

func (s *Server) Descriptor() EndpointDescriptor { return s.descriptor }

func (s *Server) Serve(ctx context.Context) error {
	go func() {
		<-ctx.Done()
		_ = s.Close()
	}()
	for {
		conn, err := s.ln.Accept()
		if err != nil {
			s.mu.Lock()
			closed := s.closed
			s.mu.Unlock()
			if closed || errors.Is(err, net.ErrClosed) {
				return nil
			}
			continue
		}
		go s.handleConn(ctx, conn)
	}
}

func (s *Server) Close() error {
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		return nil
	}
	s.closed = true
	s.mu.Unlock()
	err := s.ln.Close()
	if s.network == "unix" && s.address != "" {
		_ = os.Remove(s.address)
	}
	return err
}

func (s *Server) handleConn(ctx context.Context, conn net.Conn) {
	if err := serverHandshake(conn, s.host.HostID(), s.token); err != nil {
		_ = conn.Close()
		return
	}
	cfg := yamux.DefaultConfig()
	cfg.LogOutput = io.Discard
	mux, err := yamux.Server(conn, cfg)
	if err != nil {
		_ = conn.Close()
		return
	}
	defer mux.Close()

	for {
		stream, err := mux.Accept()
		if err != nil {
			return
		}
		go s.handleStream(ctx, stream)
	}
}

func (s *Server) handleStream(ctx context.Context, stream net.Conn) {
	defer stream.Close()
	var req rpcRequest
	if err := readJSONFrame(stream, &req); err != nil {
		return
	}
	if req.Method == "attach" {
		s.handleAttach(ctx, stream, req.Payload)
		return
	}
	res, err := s.dispatch(ctx, req.Method, req.Payload)
	if err != nil {
		_ = writeJSONFrame(stream, rpcResponse{OK: false, Code: errorCode(err), Error: err.Error()})
		return
	}
	var raw json.RawMessage
	if res != nil {
		raw, _ = json.Marshal(res)
	}
	_ = writeJSONFrame(stream, rpcResponse{OK: true, Payload: raw})
}

func (s *Server) handleAttach(ctx context.Context, stream net.Conn, payload json.RawMessage) {
	var req attachReq
	if err := json.Unmarshal(payload, &req); err != nil {
		_ = writeJSONFrame(stream, rpcResponse{OK: false, Code: "INVALID_REQUEST", Error: err.Error()})
		return
	}
	paneStream, err := s.host.Attach(ctx, req.Target, req.Opts)
	if err != nil {
		_ = writeJSONFrame(stream, rpcResponse{OK: false, Code: errorCode(err), Error: err.Error()})
		return
	}
	defer paneStream.Close()

	if err := writeJSONFrame(stream, rpcResponse{OK: true}); err != nil {
		return
	}

	// Detect remote close promptly so closing the yamux stream immediately unsubscribes.
	peerClosed := make(chan struct{})
	go func() {
		defer close(peerClosed)
		var b [1]byte
		_, _ = stream.Read(b[:])
	}()

	for {
		select {
		case <-ctx.Done():
			return
		case <-peerClosed:
			return
		case ev, ok := <-paneStream.Events():
			if !ok {
				return
			}
			if err := writeJSONFrame(stream, ev); err != nil {
				return
			}
		}
	}
}

func (s *Server) dispatch(ctx context.Context, method string, payload json.RawMessage) (any, error) {
	switch method {
	case "health":
		return healthReply{
			HostID:      s.host.HostID(),
			Protocol:    ProtocolVersion,
			ActivePanes: s.host.ActivePaneCount(),
			Draining:    s.host.IsDraining(),
			Caps:        s.host.Capabilities(),
		}, nil
	case "drain":
		s.host.SetDraining(true)
		return healthReply{
			HostID:      s.host.HostID(),
			Protocol:    ProtocolVersion,
			ActivePanes: s.host.ActivePaneCount(),
			Draining:    true,
			Caps:        s.host.Capabilities(),
		}, nil
	case "create":
		var spec sessionbackend.CreateSpec
		if err := json.Unmarshal(payload, &spec); err != nil {
			return nil, err
		}
		return s.host.Create(ctx, spec)
	case "observe":
		var r sessionIDReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return s.host.Observe(ctx, r.SessionID)
	case "list":
		return s.host.List(ctx)
	case "close":
		var r sessionIDReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return nil, s.host.Close(ctx, r.SessionID)
	case "rename":
		var r renameReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return nil, s.host.Rename(ctx, r.SessionID, r.Label)
	case "claim":
		var r claimReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return s.host.ClaimControl(ctx, r.Target, r.ClientID)
	case "release":
		var r releaseReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return nil, s.host.ReleaseControl(ctx, r.Target, r.ClientID, r.ControlGen)
	case "input":
		var r inputReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return nil, s.host.WriteInput(ctx, r.Target, r.ControlGen, r.Data)
	case "submit":
		var r submitReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return s.host.Submit(ctx, r.Target, r.Req)
	case "resize":
		var r resizeReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return nil, s.host.Resize(ctx, r.Target, r.ControlGen, r.Cols, r.Rows)
	case "move_cursor":
		var r moveCursorReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return nil, s.host.MoveCursor(ctx, r.Target, r.ControlGen, r.Col, r.Row)
	case "capture":
		var r captureReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return s.host.Capture(ctx, r.Target, r.Opts)
	case "new_window":
		lb, ok := s.host.(sessionbackend.LayoutBackend)
		if !ok {
			return nil, sessionbackend.ErrUnsupported
		}
		var r newWindowReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return lb.NewWindow(ctx, r.SessionID, r.Spec)
	case "list_windows":
		lb, ok := s.host.(sessionbackend.LayoutBackend)
		if !ok {
			return nil, sessionbackend.ErrUnsupported
		}
		var r sessionIDReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return lb.ListWindows(ctx, r.SessionID)
	case "select_window":
		lb, ok := s.host.(sessionbackend.LayoutBackend)
		if !ok {
			return nil, sessionbackend.ErrUnsupported
		}
		var r windowIDReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return nil, lb.SelectWindow(ctx, r.SessionID, r.WindowID)
	case "close_window":
		lb, ok := s.host.(sessionbackend.LayoutBackend)
		if !ok {
			return nil, sessionbackend.ErrUnsupported
		}
		var r windowIDReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return nil, lb.CloseWindow(ctx, r.SessionID, r.WindowID)
	case "split_pane":
		lb, ok := s.host.(sessionbackend.LayoutBackend)
		if !ok {
			return nil, sessionbackend.ErrUnsupported
		}
		var r splitPaneReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		win, pid, err := lb.SplitPane(ctx, r.SessionID, r.PaneID, r.Spec)
		if err != nil {
			return nil, err
		}
		return splitPaneReply{Window: win, PaneID: pid}, nil
	case "resize_split":
		lb, ok := s.host.(sessionbackend.LayoutBackend)
		if !ok {
			return nil, sessionbackend.ErrUnsupported
		}
		var r resizeSplitReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return lb.ResizeSplit(ctx, r.SessionID, r.WindowID, r.NodeID, r.Ratio, r.ExpectedVersion)
	case "focus_pane":
		lb, ok := s.host.(sessionbackend.LayoutBackend)
		if !ok {
			return nil, sessionbackend.ErrUnsupported
		}
		var r focusPaneReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return lb.FocusPane(ctx, r.SessionID, r.WindowID, r.PaneID)
	case "close_pane":
		lb, ok := s.host.(sessionbackend.LayoutBackend)
		if !ok {
			return nil, sessionbackend.ErrUnsupported
		}
		var r closePaneReq
		if err := json.Unmarshal(payload, &r); err != nil {
			return nil, err
		}
		return lb.ClosePane(ctx, r.SessionID, r.PaneID)
	default:
		return nil, sessionbackend.ErrUnsupported
	}
}
