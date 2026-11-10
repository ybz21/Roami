package modelplugins

import (
	"bufio"
	"context"
	"embed"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

//go:embed runtime/*
var runtimeFiles embed.FS

var ErrHostClosed = errors.New("MODEL_PLUGIN_HOST_CLOSED")

// Host owns one provider source's process. Launch must supply the platform's
// sandbox command; this bridge never silently launches uploaded code unsandboxed.
type Host struct {
	cmd       *exec.Cmd
	stdin     io.WriteCloser
	writeMu   sync.Mutex
	mu        sync.Mutex
	pending   map[string]chan frame
	done      chan struct{}
	closeOnce sync.Once
	sequence  atomic.Uint64
}
type frame struct {
	ID     string          `json:"id"`
	Event  string          `json:"event"`
	Result json.RawMessage `json:"result"`
	Error  *struct {
		Message string `json:"message"`
	} `json:"error"`
	Status  int               `json:"status"`
	Headers map[string]string `json:"headers"`
	Data    string            `json:"data"`
}

func MaterializeRuntime(root string) error {
	if err := os.MkdirAll(root, 0700); err != nil {
		return err
	}
	for _, name := range []string{"magpie-host.js", "magpie-pi.js", "egress-preload.mjs", "LICENSE.magpie", "NOTICE.md"} {
		data, err := runtimeFiles.ReadFile("runtime/" + name)
		if err != nil {
			return err
		}
		f, err := os.CreateTemp(root, ".runtime-")
		if err != nil {
			return err
		}
		_, err = f.Write(data)
		if closeErr := f.Close(); err == nil {
			err = closeErr
		}
		if err == nil {
			err = os.Rename(f.Name(), filepath.Join(root, name))
		}
		_ = os.Remove(f.Name())
		if err != nil {
			return err
		}
	}
	return nil
}

func StartHost(command *exec.Cmd) (*Host, error) {
	if command == nil {
		return nil, errors.New("MODEL_PLUGIN_SANDBOX_UNAVAILABLE")
	}
	stdin, err := command.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := command.StdoutPipe()
	if err != nil {
		_ = stdin.Close()
		return nil, err
	}
	// Provider logs can contain credentials; the management API does not expose them.
	command.Stderr = io.Discard
	if err = command.Start(); err != nil {
		_ = stdin.Close()
		return nil, err
	}
	h := &Host{cmd: command, stdin: stdin, pending: map[string]chan frame{}, done: make(chan struct{})}
	go h.read(stdout)
	go func() { _ = command.Wait(); h.stop() }()
	return h, nil
}
func (h *Host) stop() { h.closeOnce.Do(func() { close(h.done); _ = h.stdin.Close() }) }
func (h *Host) Close() error {
	h.stop()
	if h.cmd.Process != nil {
		return h.cmd.Process.Kill()
	}
	return nil
}
func (h *Host) read(reader io.Reader) {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 64<<10), 2<<20)
	for scanner.Scan() {
		var f frame
		if json.Unmarshal(scanner.Bytes(), &f) != nil {
			continue
		}
		if f.ID == "" {
			continue
		}
		h.mu.Lock()
		ch := h.pending[f.ID]
		h.mu.Unlock()
		if ch != nil {
			select {
			case ch <- f:
			default:
				h.stop()
				if h.cmd.Process != nil {
					_ = h.cmd.Process.Kill()
				}
				return
			case <-h.done:
				return
			}
		}
	}
	h.stop()
	if h.cmd.Process != nil {
		_ = h.cmd.Process.Kill()
	}
}
func (h *Host) send(value any) error {
	h.writeMu.Lock()
	defer h.writeMu.Unlock()
	select {
	case <-h.done:
		return ErrHostClosed
	default:
	}
	timer := time.AfterFunc(15*time.Second, func() {
		h.stop()
		if h.cmd.Process != nil {
			_ = h.cmd.Process.Kill()
		}
	})
	defer timer.Stop()
	err := json.NewEncoder(h.stdin).Encode(value)
	if err != nil {
		h.stop()
		if h.cmd.Process != nil {
			_ = h.cmd.Process.Kill()
		}
	}
	return err
}
func (h *Host) request(method string, params any) (string, chan frame, error) {
	id := strconv.FormatUint(h.sequence.Add(1), 10)
	ch := make(chan frame, 260)
	h.mu.Lock()
	if len(h.pending) >= 64 {
		h.mu.Unlock()
		return "", nil, errors.New("MODEL_PLUGIN_BUSY")
	}
	h.pending[id] = ch
	h.mu.Unlock()
	err := h.send(map[string]any{"id": id, "method": method, "params": params})
	if err != nil {
		h.release(id)
		return "", nil, err
	}
	return id, ch, nil
}
func (h *Host) release(id string) { h.mu.Lock(); delete(h.pending, id); h.mu.Unlock() }
func (h *Host) abort(id string) {
	_ = h.send(map[string]any{"method": "abort", "params": map[string]any{"id": id}})
}
func (h *Host) Call(ctx context.Context, method string, params any, result any) error {
	id, ch, err := h.request(method, params)
	if err != nil {
		return err
	}
	defer h.release(id)
	select {
	case <-ctx.Done():
		h.abort(id)
		return ctx.Err()
	case <-h.done:
		return ErrHostClosed
	case f := <-ch:
		if f.Error != nil {
			return fmt.Errorf("MODEL_PLUGIN_RPC_FAILED: %s", f.Error.Message)
		}
		if f.Event != "" {
			return errors.New("MODEL_PLUGIN_INVALID_RESPONSE")
		}
		if result == nil {
			return nil
		}
		return json.Unmarshal(f.Result, result)
	}
}

// Fetch retains Magpie's credit window, returning bytes only as its caller reads.
func (h *Host) Fetch(ctx context.Context, params map[string]any) (*http.Response, error) {
	input := make(map[string]any, len(params)+1)
	for key, value := range params {
		input[key] = value
	}
	input["window"] = 512 << 10
	id, ch, err := h.request("fetch", input)
	if err != nil {
		return nil, err
	}
	var head frame
	select {
	case <-ctx.Done():
		h.abort(id)
		h.release(id)
		return nil, ctx.Err()
	case <-h.done:
		h.release(id)
		return nil, ErrHostClosed
	case head = <-ch:
	}
	if head.Error != nil {
		h.abort(id)
		h.release(id)
		return nil, fmt.Errorf("MODEL_PLUGIN_FETCH_FAILED: %s", head.Error.Message)
	}
	if head.Event != "head" || head.Status < 100 || head.Status > 599 {
		h.abort(id)
		h.release(id)
		return nil, errors.New("MODEL_PLUGIN_FETCH_FAILED")
	}
	reader, writer := io.Pipe()
	cancel := context.AfterFunc(ctx, func() { h.abort(id); _ = writer.CloseWithError(ctx.Err()) })
	go func() {
		defer h.release(id)
		defer cancel()
		defer writer.Close()
		for {
			select {
			case <-ctx.Done():
				_ = writer.CloseWithError(ctx.Err())
				return
			case <-h.done:
				_ = writer.CloseWithError(ErrHostClosed)
				return
			case f := <-ch:
				if f.Error != nil {
					_ = writer.CloseWithError(errors.New("MODEL_PLUGIN_FETCH_FAILED"))
					return
				}
				if f.Event == "" {
					return
				}
				if f.Event != "chunk" {
					h.abort(id)
					_ = writer.CloseWithError(errors.New("MODEL_PLUGIN_INVALID_RESPONSE"))
					return
				}
				data, err := base64.StdEncoding.DecodeString(f.Data)
				if err != nil || len(data) > 64<<10 {
					h.abort(id)
					_ = writer.CloseWithError(errors.New("MODEL_PLUGIN_INVALID_RESPONSE"))
					return
				}
				if _, err = writer.Write(data); err != nil {
					h.abort(id)
					return
				}
				if err = h.send(map[string]any{"method": "credit", "params": map[string]any{"id": id, "n": len(data) + 2048}}); err != nil {
					_ = writer.CloseWithError(err)
					return
				}
			}
		}
	}()
	headers := make(http.Header, len(head.Headers))
	for k, v := range head.Headers {
		if strings.ContainsAny(k+v, "\r\n") {
			_ = reader.Close()
			h.abort(id)
			return nil, errors.New("MODEL_PLUGIN_INVALID_RESPONSE")
		}
		headers.Set(k, v)
	}
	return &http.Response{StatusCode: head.Status, Header: headers, Body: &fetchBody{PipeReader: reader, close: func() { h.abort(id); cancel() }}, ContentLength: -1}, nil
}

type fetchBody struct {
	*io.PipeReader
	once  sync.Once
	close func()
}

func (b *fetchBody) Close() error { b.once.Do(b.close); return b.PipeReader.Close() }
