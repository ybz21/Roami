package rpc

import (
	"encoding/json"
	"io"
	"testing"
	"time"
)

// pipePair wires two Conns together like host↔plugin stdio.
func pipePair(hostHandler, pluginHandler Handler) (*Conn, *Conn) {
	hr, pw := io.Pipe() // plugin writes -> host reads
	pr, hw := io.Pipe() // host writes -> plugin reads
	host := NewConn(hr, hw, hostHandler)
	pluginC := NewConn(pr, pw, pluginHandler)
	return host, pluginC
}

func TestCallRoundTrip(t *testing.T) {
	host, pluginC := pipePair(nil, func(method string, params json.RawMessage) (any, error) {
		if method != "plugin/echo" {
			t.Errorf("unexpected method %s", method)
		}
		var m map[string]string
		_ = json.Unmarshal(params, &m)
		return map[string]string{"echo": m["msg"]}, nil
	})
	defer host.Close()
	defer pluginC.Close()

	raw, err := host.Call("plugin/echo", map[string]string{"msg": "hi"}, 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]string
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	if out["echo"] != "hi" {
		t.Fatalf("want hi, got %q", out["echo"])
	}
}

func TestNestedBidirectionalCall(t *testing.T) {
	// 插件在处理 invoke 时反调宿主 roam/* —— 双向嵌套是协议的核心场景。
	var pluginC *Conn
	host, pc := pipePair(
		func(method string, params json.RawMessage) (any, error) {
			if method == "roam/data" {
				return map[string]int{"value": 42}, nil
			}
			return nil, &Error{Code: CodeUnknownMethod, Message: method}
		},
		nil,
	)
	pluginC = pc
	pluginC.handler = func(method string, params json.RawMessage) (any, error) {
		raw, err := pluginC.Call("roam/data", nil, 2*time.Second)
		if err != nil {
			return nil, err
		}
		var d map[string]int
		_ = json.Unmarshal(raw, &d)
		return map[string]int{"doubled": d["value"] * 2}, nil
	}
	defer host.Close()
	defer pluginC.Close()

	raw, err := host.Call("plugin/work", nil, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]int
	_ = json.Unmarshal(raw, &out)
	if out["doubled"] != 84 {
		t.Fatalf("want 84, got %d", out["doubled"])
	}
}

func TestErrorPropagation(t *testing.T) {
	host, pluginC := pipePair(nil, func(method string, params json.RawMessage) (any, error) {
		return nil, &Error{Code: CodePermissionDenied, Message: "permission denied: agents:spawn"}
	})
	defer host.Close()
	defer pluginC.Close()

	_, err := host.Call("plugin/x", nil, 2*time.Second)
	rpcErr, ok := err.(*Error)
	if !ok || rpcErr.Code != CodePermissionDenied {
		t.Fatalf("want permission denied rpc error, got %v", err)
	}
}

func TestStrayOutputCounted(t *testing.T) {
	// stdout 上帧外的杂散输出应计入协议错误而不是搞乱解析。
	hr, pw := io.Pipe()
	_, hw := io.Pipe()
	host := NewConn(hr, hw, nil)
	defer host.Close()

	go func() {
		pw.Write([]byte("oops a stray console.log line\n"))
		body := []byte(`{"jsonrpc":"2.0","id":99,"result":{}}`)
		pw.Write([]byte("Content-Length: " + itoa(len(body)) + "\r\n\r\n"))
		pw.Write(body)
	}()
	time.Sleep(200 * time.Millisecond)
	if host.ProtoErrors() == 0 {
		t.Fatal("stray output was not counted as protocol error")
	}
}

func itoa(n int) string {
	b, _ := json.Marshal(n)
	return string(b)
}
