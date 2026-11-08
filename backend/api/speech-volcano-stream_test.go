package api

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func streamFixture(flags byte, payload string, compressed bool) []byte {
	data := []byte(payload)
	compression := byte(0)
	if compressed {
		var buf bytes.Buffer
		w := gzip.NewWriter(&buf)
		_, _ = w.Write(data)
		_ = w.Close()
		data, compression = buf.Bytes(), 1
	}
	frame := []byte{0x11, 0x90 | flags, 0x10 | compression, 0}
	if flags&1 != 0 {
		frame = binary.BigEndian.AppendUint32(frame, uint32(7))
	}
	if flags&4 != 0 {
		frame = binary.BigEndian.AppendUint32(frame, 0)
	}
	frame = binary.BigEndian.AppendUint32(frame, uint32(len(data)))
	return append(frame, data...)
}

func TestVolcanoStreamKeyOnly(t *testing.T) {
	audio := bytes.Repeat([]byte{1, 2, 3, 4}, 3300)
	requests := make(chan []byte, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Api-Key") != "test-key" || r.Header.Get("X-Api-Resource-Id") != "volc.seedasr.sauc.duration" || r.Header.Get("X-Api-Request-Id") == "" {
			t.Errorf("incorrect authentication or model headers")
		}
		if r.Header.Get("X-Api-App-Key") != "" || r.Header.Get("X-Api-Access-Key") != "" {
			t.Error("legacy credentials must not be sent with API Key")
		}
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		defer conn.Close()
		var received []byte
		for index := 0; ; index++ {
			kind, frame, err := conn.ReadMessage()
			if err != nil {
				t.Error(err)
				return
			}
			if kind != websocket.BinaryMessage || len(frame) < 12 || frame[0] != 0x11 || frame[2]&15 != 1 {
				t.Error("incorrect binary protocol")
				return
			}
			seq := int32(binary.BigEndian.Uint32(frame[4:8]))
			wantSeq := int32(index + 1)
			if frame[1]&2 != 0 {
				wantSeq = -wantSeq
			}
			if seq != wantSeq || int(binary.BigEndian.Uint32(frame[8:12])) != len(frame)-12 {
				t.Error("incorrect sequence or payload length")
				return
			}
			reader, err := gzip.NewReader(bytes.NewReader(frame[12:]))
			if err != nil {
				t.Error(err)
				return
			}
			data, err := io.ReadAll(reader)
			reader.Close()
			if err != nil {
				t.Error(err)
				return
			}
			if index == 0 {
				if frame[1] != 0x11 || frame[2] != 0x11 {
					t.Error("incorrect initialization frame")
					return
				}
				var config struct {
					Audio struct {
						Format              string
						Rate, Bits, Channel int
					}
					Request map[string]any
				}
				if err := json.Unmarshal(data, &config); err != nil || config.Audio.Format != "wav" || config.Audio.Rate != 16000 || config.Audio.Bits != 16 || config.Audio.Channel != 1 || config.Request["model_name"] != "bigmodel" || config.Request["enable_nonstream"] != true || config.Request["result_type"] != "full" {
					t.Errorf("incorrect audio/model metadata: %s", data)
					return
				}
				_ = conn.WriteMessage(websocket.BinaryMessage, streamFixture(1, `{}`, true))
				continue
			}
			if frame[1]>>4 != 2 || frame[2]>>4 != 0 {
				t.Error("incorrect audio frame")
				return
			}
			received = append(received, data...)
			if seq < 0 {
				requests <- received
				_ = conn.WriteMessage(websocket.BinaryMessage, streamFixture(7, `{"result":{"text":"最终文本。"}}`, true))
				return
			}
			_ = conn.WriteMessage(websocket.BinaryMessage, streamFixture(1, `{"result":{"text":"临时"}}`, false))
		}
	}))
	defer server.Close()
	cfg := VolcanoSpeech{APIKey: " test-key ", AppID: "legacy-app", AccessToken: "old-token", ResourceID: "volc.bigasr.auc", Endpoint: "ws" + strings.TrimPrefix(server.URL, "http")}
	text, err := transcribeVolcano(context.Background(), cfg, audio)
	if err != nil || text != "最终文本。" {
		t.Fatalf("text=%q err=%v", text, err)
	}
	if got := <-requests; !bytes.Equal(got, audio) {
		t.Fatal("audio was truncated or changed")
	}
}

func TestVolcanoStreamDefaultsReplaceRecordingConfig(t *testing.T) {
	for _, cfg := range []VolcanoSpeech{{APIKey: "key"}, {APIKey: "key", ResourceID: "volc.bigasr.auc_turbo", Endpoint: "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"}} {
		got := volcanoStreamConfig(cfg)
		if got.Endpoint != "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async" || got.ResourceID != "volc.seedasr.sauc.duration" {
			t.Fatalf("wrong defaults: %+v", got)
		}
	}
}

func TestVolcanoStreamCancellation(t *testing.T) {
	ready := make(chan struct{})
	stopped := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		defer close(stopped)
		_, _, _ = conn.ReadMessage()
		close(ready)
		_, _, _ = conn.ReadMessage()
	}))
	defer server.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	go func() {
		_, err := transcribeVolcano(ctx, VolcanoSpeech{APIKey: "key", Endpoint: "ws" + strings.TrimPrefix(server.URL, "http")}, []byte("audio"))
		result <- err
	}()
	select {
	case <-ready:
	case <-time.After(3 * time.Second):
		t.Fatal("connection not initialized")
	}
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("err=%v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("cancel did not stop recognition")
	}
	select {
	case <-stopped:
	case <-time.After(time.Second):
		t.Fatal("connection leaked")
	}
}

func TestVolcanoStreamFrames(t *testing.T) {
	errorFrame := []byte{0x11, 0xf0, 0, 0}
	errorFrame = binary.BigEndian.AppendUint32(errorFrame, 45000001)
	errorFrame = binary.BigEndian.AppendUint32(errorFrame, uint32(len("not authorized")))
	errorFrame = append(errorFrame, "not authorized"...)
	if _, err := parseVolcanoStreamResult(errorFrame); err == nil || !strings.Contains(err.Error(), "45000001") {
		t.Fatalf("missing upstream error: %v", err)
	}
	for _, frame := range [][]byte{nil, {0x11}, {0x10, 0x90, 0x10, 0}, {0x11, 0x91, 0x11, 0}, {0x11, 0x90, 0x10, 0, 0, 0, 0, 4, '{', '}'}, streamFixture(3, `not JSON`, false)} {
		if _, err := parseVolcanoStreamResult(frame); err == nil {
			t.Errorf("accepted malformed frame %x", frame)
		}
	}
	silent, err := parseVolcanoStreamResult(streamFixture(2, `{"result":{"text":""}}`, true))
	if err != nil || !silent.Final || !silent.HasText || silent.Text != "" {
		t.Fatalf("silence: %+v %v", silent, err)
	}
	var large bytes.Buffer
	w := gzip.NewWriter(&large)
	_, _ = w.Write(bytes.Repeat([]byte("x"), volcanoResultLimit+1))
	_ = w.Close()
	frame := []byte{0x11, 0x92, 0x11, 0}
	frame = binary.BigEndian.AppendUint32(frame, uint32(large.Len()))
	frame = append(frame, large.Bytes()...)
	if _, err := parseVolcanoStreamResult(frame); err == nil {
		t.Fatal("accepted oversized decompressed result")
	}
}
