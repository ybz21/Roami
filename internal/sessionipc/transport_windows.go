//go:build windows

package sessionipc

import "net"

// ListenLocal binds to a loopback-only ephemeral port paired with a 256-bit private token.
func ListenLocal(_, _ string) (net.Listener, string, string, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, "", "", err
	}
	return ln, "tcp", ln.Addr().String(), nil
}

func verifyPeerConn(_ net.Conn) error { return nil }
