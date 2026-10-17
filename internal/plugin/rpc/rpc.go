// Package rpc implements JSON-RPC 2.0 over a byte stream with LSP-style
// Content-Length framing. 宿主与插件子进程之间、CLI 与 plugind 之间共用同一套
// 编解码;帧边界外的字节按协议错误计数(防依赖库向 stdout 偷打日志)。
package rpc

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// Message is a JSON-RPC 2.0 request, notification or response.
type Message struct {
	Jsonrpc string          `json:"jsonrpc"`
	ID      *int64          `json:"id,omitempty"`
	Method  string          `json:"method,omitempty"`
	Params  json.RawMessage `json:"params,omitempty"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *Error          `json:"error,omitempty"`
}

// Error is a JSON-RPC 2.0 error object.
type Error struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data,omitempty"`
}

func (e *Error) Error() string { return fmt.Sprintf("rpc error %d: %s", e.Code, e.Message) }

// Well-known error codes (application range).
const (
	CodePermissionDenied = -32001
	CodeUnknownMethod    = -32601
	CodeInternal         = -32603
)

// Handler serves an incoming request; params is the raw JSON params value.
type Handler func(method string, params json.RawMessage) (any, error)

// Conn drives a framed JSON-RPC 2.0 connection. Both peers act as client and
// server simultaneously (host calls plugin, plugin calls back roam/* APIs).
type Conn struct {
	w       io.Writer
	wmu     sync.Mutex
	handler Handler

	mu      sync.Mutex
	pending map[int64]chan *Message
	nextID  int64
	closed  chan struct{}
	once    sync.Once
	readErr atomic.Value // error

	// protoErrs counts bytes/lines outside frame boundaries (e.g. stray
	// console output on stdout). The owner may inspect it to mark unhealthy.
	protoErrs atomic.Int64
}

// NewConn wraps r/w and starts the read loop. handler serves peer requests
// sequentially per message (each in its own goroutine to allow nested calls).
func NewConn(r io.Reader, w io.Writer, handler Handler) *Conn {
	c := &Conn{w: w, handler: handler, pending: map[int64]chan *Message{}, closed: make(chan struct{})}
	go c.readLoop(bufio.NewReaderSize(r, 64*1024))
	return c
}

// ProtoErrors returns the count of framing violations seen so far.
func (c *Conn) ProtoErrors() int64 { return c.protoErrs.Load() }

// Close terminates the connection loop (the underlying stream is owned by the
// caller and must be closed separately).
func (c *Conn) Close() {
	c.once.Do(func() { close(c.closed) })
}

// Done is closed when the read loop terminates (EOF, error or Close).
func (c *Conn) Done() <-chan struct{} { return c.closed }

// Call sends a request and waits for its response up to timeout.
func (c *Conn) Call(method string, params any, timeout time.Duration) (json.RawMessage, error) {
	id := atomic.AddInt64(&c.nextID, 1)
	ch := make(chan *Message, 1)
	c.mu.Lock()
	c.pending[id] = ch
	c.mu.Unlock()
	defer func() {
		c.mu.Lock()
		delete(c.pending, id)
		c.mu.Unlock()
	}()
	if err := c.send(Message{Jsonrpc: "2.0", ID: &id, Method: method, Params: mustJSON(params)}); err != nil {
		return nil, err
	}
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case resp := <-ch:
		if resp.Error != nil {
			return nil, resp.Error
		}
		return resp.Result, nil
	case <-timer.C:
		return nil, fmt.Errorf("rpc timeout after %s calling %s", timeout, method)
	case <-c.closed:
		if err, ok := c.readErr.Load().(error); ok && err != nil {
			return nil, fmt.Errorf("rpc connection closed calling %s: %w", method, err)
		}
		return nil, fmt.Errorf("rpc connection closed calling %s", method)
	}
}

// Notify sends a notification (no response expected).
func (c *Conn) Notify(method string, params any) error {
	return c.send(Message{Jsonrpc: "2.0", Method: method, Params: mustJSON(params)})
}

func (c *Conn) send(m Message) error {
	body, err := json.Marshal(m)
	if err != nil {
		return err
	}
	c.wmu.Lock()
	defer c.wmu.Unlock()
	if _, err := fmt.Fprintf(c.w, "Content-Length: %d\r\n\r\n", len(body)); err != nil {
		return err
	}
	_, err = c.w.Write(body)
	return err
}

func (c *Conn) readLoop(r *bufio.Reader) {
	defer c.Close()
	for {
		select {
		case <-c.closed:
			return
		default:
		}
		body, err := readFrame(r, &c.protoErrs)
		if err != nil {
			if !errors.Is(err, io.EOF) {
				c.readErr.Store(err)
			}
			return
		}
		var m Message
		if err := json.Unmarshal(body, &m); err != nil {
			c.protoErrs.Add(1)
			continue
		}
		switch {
		case m.Method != "" && m.ID != nil: // request
			go c.serve(m)
		case m.Method != "": // notification
			go func(m Message) {
				if c.handler != nil {
					_, _ = c.handler(m.Method, m.Params)
				}
			}(m)
		case m.ID != nil: // response
			c.mu.Lock()
			ch := c.pending[*m.ID]
			c.mu.Unlock()
			if ch != nil {
				mm := m
				ch <- &mm
			}
		}
	}
}

func (c *Conn) serve(req Message) {
	resp := Message{Jsonrpc: "2.0", ID: req.ID}
	if c.handler == nil {
		resp.Error = &Error{Code: CodeUnknownMethod, Message: "no handler"}
	} else {
		result, err := c.handler(req.Method, req.Params)
		if err != nil {
			var rpcErr *Error
			if errors.As(err, &rpcErr) {
				resp.Error = rpcErr
			} else {
				resp.Error = &Error{Code: CodeInternal, Message: err.Error()}
			}
		} else {
			resp.Result = mustJSON(result)
		}
	}
	_ = c.send(resp)
}

// readFrame parses one Content-Length framed body. Garbage before a valid
// header line increments protoErrs and is skipped line by line.
func readFrame(r *bufio.Reader, protoErrs *atomic.Int64) ([]byte, error) {
	var length int
	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return nil, err
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "" {
			if length > 0 {
				break // end of headers
			}
			continue
		}
		if v, ok := strings.CutPrefix(line, "Content-Length:"); ok {
			n, err := strconv.Atoi(strings.TrimSpace(v))
			if err != nil || n <= 0 || n > 64*1024*1024 {
				protoErrs.Add(1)
				continue
			}
			length = n
			continue
		}
		if strings.Contains(line, ":") && length == 0 {
			continue // other header, tolerated
		}
		protoErrs.Add(1) // stray bytes outside frame
	}
	body := make([]byte, length)
	if _, err := io.ReadFull(r, body); err != nil {
		return nil, err
	}
	return body, nil
}

func mustJSON(v any) json.RawMessage {
	if v == nil {
		return json.RawMessage("null")
	}
	if raw, ok := v.(json.RawMessage); ok {
		return raw
	}
	b, err := json.Marshal(v)
	if err != nil {
		b = []byte("null")
	}
	return b
}
