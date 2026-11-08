package api

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

const (
	volcanoStreamEndpoint = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
	volcanoStreamResource = "volc.seedasr.sauc.duration"
	volcanoResultLimit    = 4 << 20
	volcanoAudioChunk     = 6400 // 200ms of the recorder's 16kHz mono PCM WAV.
)

func volcanoStreamConfig(cfg VolcanoSpeech) VolcanoSpeech {
	cfg.APIKey = strings.TrimSpace(cfg.APIKey)
	// Saved recording-file endpoints and resource IDs cannot serve streaming keys.
	if !strings.HasPrefix(cfg.Endpoint, "wss://") && !strings.HasPrefix(cfg.Endpoint, "ws://") {
		cfg.Endpoint = volcanoStreamEndpoint
	}
	if !strings.Contains(cfg.ResourceID, ".sauc.") {
		cfg.ResourceID = volcanoStreamResource
	}
	return cfg
}

func transcribeVolcanoStream(ctx context.Context, cfg VolcanoSpeech, audio []byte) (string, error) {
	if len(audio) == 0 {
		return "", fmt.Errorf("volcano: empty audio")
	}
	cfg = volcanoStreamConfig(cfg)
	ctx, cancel := context.WithTimeout(ctx, time.Duration(len(audio))*time.Second/32000+30*time.Second)
	defer cancel()
	headers := http.Header{}
	headers.Set("X-Api-Key", cfg.APIKey)
	headers.Set("X-Api-Resource-Id", cfg.ResourceID)
	headers.Set("X-Api-Request-Id", randomID())
	dialer := *websocket.DefaultDialer
	dialer.HandshakeTimeout = 10 * time.Second
	conn, response, err := dialer.DialContext(ctx, cfg.Endpoint, headers)
	if err != nil {
		if response != nil {
			response.Body.Close()
			return "", fmt.Errorf("volcano: websocket handshake HTTP %d", response.StatusCode)
		}
		return "", fmt.Errorf("volcano: websocket connection: %w", err)
	}
	defer conn.Close()
	stop := context.AfterFunc(ctx, func() { conn.Close() })
	defer stop()
	deadline, _ := ctx.Deadline()
	conn.SetReadDeadline(deadline)
	conn.SetWriteDeadline(deadline)
	conn.SetReadLimit(volcanoResultLimit)
	metadata, err := json.Marshal(map[string]any{
		"user":    map[string]any{"uid": "roami"},
		"audio":   map[string]any{"format": "wav", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
		"request": map[string]any{"model_name": "bigmodel", "enable_itn": true, "enable_punc": true, "enable_nonstream": true, "result_type": "full"},
	})
	if err != nil {
		return "", err
	}
	full, err := volcanoStreamFrame(1, 1, metadata)
	if err != nil {
		return "", err
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, full); err != nil {
		return "", err
	}
	read := func() (volcanoStreamResult, error) {
		kind, frame, err := conn.ReadMessage()
		if err != nil {
			if ctx.Err() != nil {
				return volcanoStreamResult{}, ctx.Err()
			}
			return volcanoStreamResult{}, fmt.Errorf("volcano: read result: %w", err)
		}
		if kind != websocket.BinaryMessage {
			return volcanoStreamResult{}, fmt.Errorf("volcano: expected a binary result")
		}
		return parseVolcanoStreamResult(frame)
	}
	if _, err := read(); err != nil {
		return "", err
	}
	// Drain results while uploading so long recordings cannot deadlock on socket buffers.
	upload := make(chan error, 1)
	go func() {
		ticker := time.NewTicker(200 * time.Millisecond)
		defer ticker.Stop()
		for offset, seq := 0, int32(2); offset < len(audio); seq++ {
			if offset > 0 {
				select {
				case <-ticker.C:
				case <-ctx.Done():
					upload <- ctx.Err()
					conn.Close()
					return
				}
			}
			end := min(offset+volcanoAudioChunk, len(audio))
			sequence := seq
			if end == len(audio) {
				sequence = -seq
			}
			frame, err := volcanoStreamFrame(2, sequence, audio[offset:end])
			if err == nil {
				err = conn.WriteMessage(websocket.BinaryMessage, frame)
			}
			if err != nil {
				upload <- err
				conn.Close()
				return
			}
			offset = end
		}
		upload <- nil
	}()
	text := ""
	for {
		result, err := read()
		if err != nil {
			return "", err
		}
		if result.HasText {
			text = result.Text
		}
		if result.Final {
			if err := <-upload; err != nil {
				return "", fmt.Errorf("volcano: upload audio: %w", err)
			}
			return text, nil
		}
	}
}

func volcanoStreamFrame(kind byte, sequence int32, payload []byte) ([]byte, error) {
	var compressed bytes.Buffer
	w := gzip.NewWriter(&compressed)
	if _, err := w.Write(payload); err != nil {
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	flags, serialization := byte(1), byte(0)
	if sequence < 0 {
		flags = 3
	}
	if kind == 1 {
		serialization = 1
	}
	frame := make([]byte, 12+compressed.Len())
	copy(frame, []byte{0x11, kind<<4 | flags, serialization<<4 | 1, 0})
	binary.BigEndian.PutUint32(frame[4:8], uint32(sequence))
	binary.BigEndian.PutUint32(frame[8:12], uint32(compressed.Len()))
	copy(frame[12:], compressed.Bytes())
	return frame, nil
}

type volcanoStreamResult struct {
	Text    string
	HasText bool
	Final   bool
}

func parseVolcanoStreamResult(frame []byte) (volcanoStreamResult, error) {
	var result volcanoStreamResult
	invalid := func() (volcanoStreamResult, error) { return result, fmt.Errorf("volcano: invalid result frame") }
	if len(frame) < 4 || frame[0]>>4 != 1 {
		return invalid()
	}
	header := int(frame[0]&15) * 4
	if header < 4 || header > len(frame) {
		return invalid()
	}
	flags, kind := frame[1]&15, frame[1]>>4
	payload := frame[header:]
	for _, flag := range []byte{1, 4} {
		if flags&flag != 0 {
			if len(payload) < 4 {
				return invalid()
			}
			payload = payload[4:]
		}
	}
	result.Final = flags&2 != 0
	var code uint32
	if kind == 15 {
		if len(payload) < 4 {
			return invalid()
		}
		code = binary.BigEndian.Uint32(payload[:4])
		payload = payload[4:]
	} else if kind != 9 {
		return invalid()
	}
	if len(payload) < 4 || uint64(binary.BigEndian.Uint32(payload[:4])) != uint64(len(payload)-4) {
		return invalid()
	}
	payload = payload[4:]
	switch frame[2] & 15 {
	case 0:
	case 1:
		r, err := gzip.NewReader(bytes.NewReader(payload))
		if err != nil {
			return invalid()
		}
		defer r.Close()
		payload, err = io.ReadAll(io.LimitReader(r, volcanoResultLimit+1))
		if err != nil || len(payload) > volcanoResultLimit {
			return invalid()
		}
	default:
		return invalid()
	}
	if kind == 15 {
		return result, fmt.Errorf("volcano ASR %d: %s", code, truncate(string(payload), 200))
	}
	if frame[2]>>4 != 1 {
		return invalid()
	}
	var body struct {
		Result *struct {
			Text string `json:"text"`
		} `json:"result"`
		Error string `json:"error"`
	}
	if err := json.Unmarshal(payload, &body); err != nil {
		return invalid()
	}
	if body.Error != "" {
		return result, fmt.Errorf("volcano ASR: %s", truncate(body.Error, 200))
	}
	if body.Result != nil {
		result.Text, result.HasText = body.Result.Text, true
	}
	return result, nil
}
