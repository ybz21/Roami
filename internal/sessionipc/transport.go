// Package sessionipc implements the yamux-multiplexed local IPC transport,
// peer/token authentication, server, client, and detached host spawner for roami-term.
package sessionipc

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"time"
)

const (
	ProtocolVersion = 1
	maxFrameBytes   = 16 << 20 // 16 MiB safety cap per IPC frame
	handshakeMagic  = "ROAMI-SESSIOND-V1\n"
)

// EndpointDescriptor is persisted in a 0600 file so local clients can discover and authenticate to a host.
type EndpointDescriptor struct {
	HostID      string `json:"hostId"`
	Network     string `json:"network"` // "unix" or "tcp"
	Address     string `json:"address"`
	Token       string `json:"token"`
	ProtocolMin int    `json:"protocolMin"`
	ProtocolMax int    `json:"protocolMax"`
	PID         int    `json:"pid"`
}

func GenerateToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func WriteEndpointDescriptor(path string, desc EndpointDescriptor) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	raw, err := json.Marshal(desc)
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, raw, 0600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func ReadEndpointDescriptor(path string) (EndpointDescriptor, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return EndpointDescriptor{}, err
	}
	var desc EndpointDescriptor
	if err := json.Unmarshal(raw, &desc); err != nil {
		return EndpointDescriptor{}, err
	}
	if desc.Address == "" || desc.Token == "" {
		return EndpointDescriptor{}, errors.New("sessionipc: incomplete endpoint descriptor")
	}
	return desc, nil
}

type authHello struct {
	Version int    `json:"version"`
	Token   string `json:"token"`
}

type authAck struct {
	OK      bool   `json:"ok"`
	HostID  string `json:"hostId,omitempty"`
	Version int    `json:"version,omitempty"`
	Error   string `json:"error,omitempty"`
}

func writeFrame(w io.Writer, payload []byte) error {
	if len(payload) > maxFrameBytes {
		return fmt.Errorf("sessionipc: frame too large (%d bytes)", len(payload))
	}
	var hdr [4]byte
	binary.BigEndian.PutUint32(hdr[:], uint32(len(payload)))
	if _, err := w.Write(hdr[:]); err != nil {
		return err
	}
	_, err := w.Write(payload)
	return err
}

func readFrame(r io.Reader) ([]byte, error) {
	var hdr [4]byte
	if _, err := io.ReadFull(r, hdr[:]); err != nil {
		return nil, err
	}
	n := binary.BigEndian.Uint32(hdr[:])
	if n > maxFrameBytes {
		return nil, fmt.Errorf("sessionipc: frame exceeds limit (%d bytes)", n)
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(r, buf); err != nil {
		return nil, err
	}
	return buf, nil
}

func writeJSONFrame(w io.Writer, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return writeFrame(w, b)
}

func readJSONFrame(r io.Reader, out any) error {
	b, err := readFrame(r)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, out)
}

func serverHandshake(conn net.Conn, hostID, expectedToken string) error {
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	defer func() { _ = conn.SetDeadline(time.Time{}) }()

	if err := verifyPeerConn(conn); err != nil {
		_ = writeJSONFrame(conn, authAck{OK: false, Error: "peer authentication failed"})
		return err
	}
	var hello authHello
	if err := readJSONFrame(conn, &hello); err != nil {
		return err
	}
	if hello.Version != ProtocolVersion {
		_ = writeJSONFrame(conn, authAck{OK: false, Error: "protocol version mismatch"})
		return fmt.Errorf("sessionipc: unsupported protocol version %d", hello.Version)
	}
	if subtle.ConstantTimeCompare([]byte(hello.Token), []byte(expectedToken)) != 1 {
		_ = writeJSONFrame(conn, authAck{OK: false, Error: "invalid token"})
		return errors.New("sessionipc: invalid auth token")
	}
	return writeJSONFrame(conn, authAck{OK: true, HostID: hostID, Version: ProtocolVersion})
}

func clientHandshake(conn net.Conn, token string) (authAck, error) {
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	defer func() { _ = conn.SetDeadline(time.Time{}) }()

	if err := writeJSONFrame(conn, authHello{Version: ProtocolVersion, Token: token}); err != nil {
		return authAck{}, err
	}
	var ack authAck
	if err := readJSONFrame(conn, &ack); err != nil {
		return authAck{}, err
	}
	if !ack.OK {
		return ack, fmt.Errorf("sessionipc: handshake rejected: %s", ack.Error)
	}
	return ack, nil
}
